package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/minio/selfupdate"
)

const releasesURL = "https://api.github.com/repos/nickadminroot/tmm-cli/releases/latest"
const releaseAssetPrefix = "https://github.com/nickadminroot/tmm-cli/releases/download/"
const maxReleaseAsset = 32 << 20
const maxExecutable = 64 << 20

type githubAsset struct {
	Name   string `json:"name"`
	URL    string `json:"browser_download_url"`
	Digest string `json:"digest"`
	Size   int64  `json:"size"`
}

type githubRelease struct {
	Tag    string        `json:"tag_name"`
	Assets []githubAsset `json:"assets"`
}

func versionParts(value string) ([3]int, bool) {
	var parts [3]int
	value = strings.TrimPrefix(value, "v")
	fields := strings.Split(value, ".")
	if len(fields) != 3 {
		return parts, false
	}
	for i, field := range fields {
		if field == "" || strings.Trim(field, "0123456789") != "" {
			return parts, false
		}
		n, err := strconv.Atoi(field)
		if err != nil {
			return parts, false
		}
		parts[i] = n
	}
	return parts, true
}

func newerVersion(remote, local string) bool {
	r, rok := versionParts(remote)
	l, lok := versionParts(local)
	if !rok || !lok {
		return false
	}
	for i := range r {
		if r[i] != l[i] {
			return r[i] > l[i]
		}
	}
	return false
}

func getRelease(client *http.Client) (githubRelease, error) {
	var release githubRelease
	req, err := http.NewRequest(http.MethodGet, releasesURL, nil)
	if err != nil {
		return release, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "tmm-cli-updater")
	resp, err := client.Do(req)
	if err != nil {
		return release, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return release, fmt.Errorf("GitHub release status %d", resp.StatusCode)
	}
	err = json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&release)
	return release, err
}

func releaseAsset(release githubRelease, goos, goarch string) (githubAsset, bool) {
	version := strings.TrimPrefix(release.Tag, "tmm-cli/v")
	if release.Tag != "tmm-cli/v"+version {
		return githubAsset{}, false
	}
	extension := ".tar.gz"
	if goos == "windows" {
		extension = ".zip"
	}
	name := fmt.Sprintf("tmm-cli_%s_%s_%s%s", version, goos, goarch, extension)
	for _, asset := range release.Assets {
		if asset.Name == name && asset.Size > 0 && asset.Size <= maxReleaseAsset &&
			strings.HasPrefix(asset.URL, releaseAssetPrefix+release.Tag+"/") &&
			strings.HasPrefix(asset.Digest, "sha256:") && len(asset.Digest) == 71 {
			return asset, true
		}
	}
	return githubAsset{}, false
}

func downloadExecutable(client *http.Client, asset githubAsset, goos string) ([]byte, error) {
	req, err := http.NewRequest(http.MethodGet, asset.URL, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "tmm-cli-updater")
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GitHub asset status %d", resp.StatusCode)
	}
	archive, err := io.ReadAll(io.LimitReader(resp.Body, maxReleaseAsset+1))
	if err != nil || len(archive) == 0 || len(archive) > maxReleaseAsset || int64(len(archive)) != asset.Size {
		return nil, errors.New("release asset size mismatch")
	}
	sum := sha256.Sum256(archive)
	if !strings.EqualFold(hex.EncodeToString(sum[:]), strings.TrimPrefix(asset.Digest, "sha256:")) {
		return nil, errors.New("release asset SHA-256 mismatch")
	}
	name := "tmm-cli"
	if goos == "windows" {
		name += ".exe"
		reader, err := zip.NewReader(bytes.NewReader(archive), int64(len(archive)))
		if err != nil {
			return nil, err
		}
		for _, file := range reader.File {
			if file.Name != name || file.UncompressedSize64 > maxExecutable {
				continue
			}
			rc, err := file.Open()
			if err != nil {
				return nil, err
			}
			binary, readErr := io.ReadAll(io.LimitReader(rc, maxExecutable+1))
			closeErr := rc.Close()
			if readErr != nil || closeErr != nil || len(binary) == 0 || len(binary) > maxExecutable {
				return nil, errors.New("invalid release executable")
			}
			return binary, nil
		}
		return nil, errors.New("release executable missing")
	}
	gz, err := gzip.NewReader(bytes.NewReader(archive))
	if err != nil {
		return nil, err
	}
	defer gz.Close()
	tarReader := tar.NewReader(gz)
	for {
		header, err := tarReader.Next()
		if err != nil {
			return nil, err
		}
		if header.Name == name && header.Typeflag == tar.TypeReg && header.Size > 0 && header.Size <= maxExecutable {
			return io.ReadAll(io.LimitReader(tarReader, maxExecutable+1))
		}
	}
}

// updateAtStartup runs only in published builds. An offline or read-only host
// keeps using its current binary; normal command output stays on stdout.
func updateAtStartup(version string, originalArgs []string) (bool, int, error) {
	if _, ok := versionParts(version); !ok {
		return false, 0, nil
	}
	client := &http.Client{Timeout: 3 * time.Second}
	release, err := getRelease(client)
	if err != nil {
		return false, 0, err
	}
	remote := strings.TrimPrefix(release.Tag, "tmm-cli/v")
	if !newerVersion(remote, version) {
		return false, 0, nil
	}
	asset, ok := releaseAsset(release, runtime.GOOS, runtime.GOARCH)
	if !ok {
		return false, 0, errors.New("matching verified release asset unavailable")
	}
	binary, err := downloadExecutable(&http.Client{Timeout: 30 * time.Second}, asset, runtime.GOOS)
	if err != nil {
		return false, 0, err
	}
	current, err := os.Executable()
	if err != nil {
		return false, 0, err
	}
	if err := selfupdate.Apply(bytes.NewReader(binary), selfupdate.Options{}); err != nil {
		return false, 0, err
	}
	fmt.Fprintf(os.Stderr, "tmm: updated to %s from GitHub release\n", remote)
	command := exec.Command(current, originalArgs...)
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	command.Stdin = os.Stdin
	if err = command.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			return true, exitErr.ExitCode(), nil
		}
		return true, 6, err
	}
	return true, 0, nil
}
