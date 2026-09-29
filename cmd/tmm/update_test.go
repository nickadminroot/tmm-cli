package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net/http"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) { return fn(req) }

func TestVersionAndAssetSelection(t *testing.T) {
	if !newerVersion("0.1.8", "0.1.7") || newerVersion("0.1.7", "0.1.7") || newerVersion("bad", "0.1.7") {
		t.Fatal("release version ordering is incorrect")
	}
	release := githubRelease{
		Tag: "tmm-cli/v0.1.8",
		Assets: []githubAsset{{
			Name: "tmm-cli_0.1.8_linux_amd64.tar.gz", Size: 10,
			URL:    releaseAssetPrefix + "tmm-cli/v0.1.8/tmm-cli_0.1.8_linux_amd64.tar.gz",
			Digest: "sha256:" + string(bytes.Repeat([]byte{'a'}, 64)),
		}},
	}
	if _, ok := releaseAsset(release, "linux", "amd64"); !ok {
		t.Fatal("valid release asset was not selected")
	}
	release.Assets[0].URL = "https://example.org/injected.tar.gz"
	if _, ok := releaseAsset(release, "linux", "amd64"); ok {
		t.Fatal("foreign download host was accepted")
	}
}

func TestDownloadExecutableVerifiesDigest(t *testing.T) {
	var archive bytes.Buffer
	gz := gzip.NewWriter(&archive)
	tw := tar.NewWriter(gz)
	binary := []byte("verified CLI executable")
	if err := tw.WriteHeader(&tar.Header{Name: "tmm-cli", Mode: 0o755, Size: int64(len(binary))}); err != nil {
		t.Fatal(err)
	}
	if _, err := tw.Write(binary); err != nil {
		t.Fatal(err)
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(archive.Bytes())
	asset := githubAsset{URL: "https://example.test/asset", Size: int64(archive.Len()), Digest: "sha256:" + hex.EncodeToString(sum[:])}
	client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(archive.Bytes()))}, nil
	})}
	got, err := downloadExecutable(client, asset, "linux")
	if err != nil || !bytes.Equal(got, binary) {
		t.Fatalf("verified archive extraction failed: %v", err)
	}
	asset.Digest = "sha256:" + string(bytes.Repeat([]byte{'0'}, 64))
	if _, err := downloadExecutable(client, asset, "linux"); err == nil {
		t.Fatal("corrupt digest was accepted")
	}
}
