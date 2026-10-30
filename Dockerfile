# Build context is the prepared patched source directory, not this repo root.
# These builder digests are retained from the pinned upstream Dockerfile.
FROM oven/bun:1@sha256:0733e50325078969732ebe3b15ce4c4be5082f18c4ac1a0f0ca4839c2e4e42a7 AS web
WORKDIR /build
RUN test "$(bun --version)" = '1.4.4'
COPY web/package.json web/bun.lock ./
RUN bun install --frozen-lockfile
COPY web/ ./
# pkce.3 includes native pricing details; rebuild instead of reusing older assets.
RUN DISABLE_ESLINT_PLUGIN=true VITE_REACT_APP_VERSION=v0.13.2-pkce.3 bun run build

FROM golang:1.26.1-alpine@sha256:2389ebfa5b7f43eeafbd6be0c3700cc46690ef842ad962f6c5bd6be49ed82039 AS server
ENV GO111MODULE=on CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOEXPERIMENT=greenteagc
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
COPY --from=web /build/dist ./web/dist
RUN go build -buildvcs=false -ldflags '-s -w -X github.com/QuantumNous/new-api/common.Version=v0.13.2-pkce.3' -o /new-api .

FROM calciumion/new-api:v0.13.2@sha256:81da2c875f1de1460e6dd30324c5cb36b23ef55eaae00f317621fcb8a701ad43
COPY --from=server --chmod=0755 /new-api /new-api
