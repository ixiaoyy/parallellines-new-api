// 仅为显式隔离测试目录准备全新 SQLite；不连接任何业务服务，不读取真实 .env。
// 从已准备候选的 source 目录 go run 本文件，复用该版本现有模块，不安装依赖。
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/glebarez/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

const testMarker = "parallellines-unified-local-test"

// readTestSecret 只读取显式测试文件中的单个合成值；有上限，错误不回显文件内容。
func readTestSecret(path string, minimum, maximum int) (string, error) {
	info, err := os.Stat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() > 4096 {
		return "", errors.New("invalid synthetic secret file")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", errors.New("synthetic secret file could not be read")
	}
	value := strings.TrimSpace(string(raw))
	if len(value) < minimum || len(value) > maximum || strings.ContainsAny(value, "\r\n") {
		return "", errors.New("synthetic secret length or format is invalid")
	}
	return value, nil
}

// seed 创建仅含本地恢复 Root、原 RP provider 和原生选项的新库；已有文件一律不覆盖。
func seed(root, passwordFile, clientSecretFile string, execute bool) error {
	if !filepath.IsAbs(root) {
		return errors.New("absolute isolated test root required")
	}
	root = filepath.Clean(root)
	marker, err := os.ReadFile(filepath.Join(root, ".pl-unified-test-root"))
	if err != nil || strings.TrimSpace(string(marker)) != testMarker {
		return errors.New("explicit isolated test root marker required")
	}
	database := filepath.Join(root, "data", "new-api.db")
	mfaFile := filepath.Join(root, "data", "root-recovery-mfa.json")
	for _, path := range []string{database, mfaFile} {
		if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
			return errors.New("test output already exists or cannot be inspected")
		}
	}
	plan := map[string]any{"execute": execute, "database": database, "root_uid": 1,
		"provider_id": 1, "client_id": "parallellines-newapi", "issuer": "https://pingxingxian.space/auth/oidc",
		"callback": "https://api.pingxingxian.space/oauth/pingxingxian", "model_channels": 0,
		"main_accounts": "created by real OIDC, not seeded", "mfa_file": mfaFile}
	if !execute {
		return json.NewEncoder(os.Stdout).Encode(plan)
	}
	password, err := readTestSecret(passwordFile, 8, 72)
	if err != nil {
		return err
	}
	clientSecret, err := readTestSecret(clientSecretFile, 16, 512)
	if err != nil {
		return err
	}
	passwordHash, err := common.Password2Hash(password)
	if err != nil {
		return errors.New("synthetic password hashing failed")
	}
	mfa, err := common.GenerateTOTPSecret("local-root")
	if err != nil {
		return errors.New("synthetic MFA generation failed")
	}
	codes, err := common.GenerateBackupCodes()
	if err != nil {
		return errors.New("synthetic backup code generation failed")
	}
	backupRows := make([]model.TwoFABackupCode, 0, len(codes))
	for _, code := range codes {
		hash, err := common.HashBackupCode(code)
		if err != nil {
			return errors.New("synthetic backup code hashing failed")
		}
		backupRows = append(backupRows, model.TwoFABackupCode{UserId: 1, CodeHash: hash})
	}
	if err := os.MkdirAll(filepath.Dir(database), 0700); err != nil {
		return err
	}
	// 排他创建同时阻止误覆盖和检查后被另一运行器创建的竞态；失败产物保留供检查，不自动删除。
	reserved, err := os.OpenFile(database, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return errors.New("new isolated SQLite file could not be reserved")
	}
	if err := reserved.Close(); err != nil {
		return err
	}
	db, err := gorm.Open(sqlite.Open(database), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	if err != nil {
		return errors.New("isolated SQLite open failed")
	}
	sqlDB, err := db.DB()
	if err != nil {
		return err
	}
	defer sqlDB.Close()
	if err := db.AutoMigrate(&model.User{}, &model.Setup{}, &model.CustomOAuthProvider{}, &model.Option{}, &model.TwoFA{}, &model.TwoFABackupCode{}); err != nil {
		return errors.New("isolated seed schema migration failed")
	}
	provider := model.CustomOAuthProvider{Id: 1, Name: "平行线", Slug: "pingxingxian", Enabled: true,
		ClientId: "parallellines-newapi", ClientSecret: clientSecret, AuthStyle: 2,
		AuthorizationEndpoint: "https://pingxingxian.space/auth/oidc/auth", TokenEndpoint: "https://pingxingxian.space/auth/oidc/token",
		UserInfoEndpoint: "https://pingxingxian.space/auth/oidc/me", Scopes: "openid profile email", UserIdField: "sub",
		UsernameField: "preferred_username", DisplayNameField: "name", EmailField: "email"}
	rootUser := model.User{Id: 1, Username: "local-root", DisplayName: "Local Root", Password: passwordHash,
		Role: common.RoleRootUser, Status: common.UserStatusEnabled, Email: "root@integration.invalid", Group: "default", AffCode: "isolated-root"}
	options := []model.Option{{Key: "ServerAddress", Value: "https://api.pingxingxian.space"},
		{Key: "PasswordLoginEnabled", Value: "true"}, {Key: "RegisterEnabled", Value: "true"},
		{Key: "QuotaForNewUser", Value: "0"}, {Key: "TurnstileCheckEnabled", Value: "false"}}
	if err := db.Transaction(func(tx *gorm.DB) error {
		for _, value := range []any{&rootUser, &provider, &options, &model.Setup{Version: "v0.13.2-pkce.10", InitializedAt: time.Now().Unix()},
			&model.TwoFA{UserId: 1, Secret: mfa.Secret(), IsEnabled: true}, &backupRows} {
			if err := tx.Create(value).Error; err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		return errors.New("isolated seed transaction failed")
	}
	// 这里只保存本次随机合成 MFA，不输出任何凭据；测试 owner 负责该目录的生命周期。
	file, err := os.OpenFile(mfaFile, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return errors.New("isolated MFA file creation failed")
	}
	if err := json.NewEncoder(file).Encode(map[string]any{"root_uid": 1, "username": "local-root", "totp_secret": mfa.Secret(), "backup_codes": codes}); err != nil {
		file.Close()
		return errors.New("isolated MFA file write failed")
	}
	if err := file.Close(); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(plan)
}

func main() {
	root := flag.String("test-root", "", "absolute marked isolated test directory")
	password := flag.String("root-password-file", "", "synthetic Root password file; never printed")
	secret := flag.String("client-secret-file", "", "synthetic NewAPI RP secret file; never printed")
	execute := flag.Bool("execute", false, "create new isolated database; default previews only")
	flag.Parse()
	if err := seed(*root, *password, *secret, *execute); err != nil {
		fmt.Fprintln(os.Stderr, err.Error())
		os.Exit(1)
	}
}
