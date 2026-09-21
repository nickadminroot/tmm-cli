package bundle

import (
	"archive/zip"
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// Bundle builds the ZIP of regular files at slash-separated logical paths.
type Bundle struct {
	Data       []byte
	Entrypoint string
}

// UsageError marks local input/argument failures (exit 2).
type UsageError struct{ msg string }

func (e *UsageError) Error() string { return e.msg }

// SingleFile bundles one input file under workspace/<name>.
func SingleFile(inputPath string) (*Bundle, error) {
	return singleFile(inputPath, "workspace/"+filepath.Base(inputPath))
}

// ModelFile bundles a YAML mechanism under the canonical linkage entrypoint.
func ModelFile(inputPath string) (*Bundle, error) {
	return singleFile(inputPath, "workspace/model.yaml")
}

func singleFile(inputPath, logical string) (*Bundle, error) {
	info, err := os.Stat(inputPath)
	if err != nil {
		return nil, &UsageError{msg: fmt.Sprintf("input %s: %v", inputPath, err)}
	}
	if info.IsDir() {
		return nil, &UsageError{msg: fmt.Sprintf("input %s is a directory", inputPath)}
	}
	data, err := os.ReadFile(inputPath)
	if err != nil {
		return nil, &UsageError{msg: err.Error()}
	}
	buf := &bytes.Buffer{}
	w := zip.NewWriter(buf)
	fw, err := w.Create(logical)
	if err != nil {
		return nil, err
	}
	if _, werr := fw.Write(data); werr != nil {
		return nil, werr
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	return &Bundle{Data: buf.Bytes(), Entrypoint: logical}, nil
}

func newUUIDv4() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16]), nil
}

// Manifest mirrors _tmm-result.json inside every result ZIP.
type Manifest struct {
	Version           int    `json:"version"`
	Operation         string `json:"operation"`
	DescriptorVersion int    `json:"descriptor_version"`
	ProducerVersion   int    `json:"producer_version"`
	Publication       string `json:"publication"`
	Entries           []struct {
		Path   string `json:"path"`
		Role   string `json:"role"`
		Page   int    `json:"page"`
		Size   int64  `json:"size"`
		SHA256 string `json:"sha256"`
	} `json:"entries"`
}

func requiresLinkageProducerFence(operation string) bool {
	switch operation {
	case "linkage", "linkage-preview", "linkage-force-preview",
		"linkage-publication-source", "linkage-xmcd-preview",
		"linkage-snapshot", "linkage-xmcd",
		"linkage-cdw-scene-plan", "linkage-cdw-page-plan":
		return true
	default:
		return false
	}
}

func ReadManifest(zipData []byte) (*Manifest, error) {
	const maxResultBytes = 128 << 20
	reader, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil {
		return nil, fmt.Errorf("result is not a valid ZIP: %w", err)
	}
	files := make(map[string]*zip.File, len(reader.File))
	var total uint64
	for _, file := range reader.File {
		if _, duplicate := files[file.Name]; duplicate {
			return nil, fmt.Errorf("result ZIP has duplicate member %s", file.Name)
		}
		if (file.Name != "_tmm-result.json" && !validResultPath(file.Name)) || file.FileInfo().IsDir() || file.FileInfo().Mode()&os.ModeSymlink != 0 {
			return nil, fmt.Errorf("result ZIP member path is invalid")
		}
		if file.UncompressedSize64 > maxResultBytes {
			return nil, fmt.Errorf("result ZIP member is too large")
		}
		total += file.UncompressedSize64
		if total > maxResultBytes {
			return nil, fmt.Errorf("result ZIP is too large")
		}
		files[file.Name] = file
	}
	manifestFile, ok := files["_tmm-result.json"]
	if !ok {
		return nil, fmt.Errorf("result ZIP has no _tmm-result.json")
	}
	manifestReader, err := manifestFile.Open()
	if err != nil {
		return nil, err
	}
	raw, err := io.ReadAll(io.LimitReader(manifestReader, 1<<20+1))
	manifestReader.Close()
	if err != nil {
		return nil, err
	}
	if len(raw) > 1<<20 {
		return nil, fmt.Errorf("_tmm-result.json is too large")
	}
	var root map[string]json.RawMessage
	if err := json.Unmarshal(raw, &root); err != nil {
		return nil, fmt.Errorf("_tmm-result.json is invalid")
	}
	var operation string
	if err := json.Unmarshal(root["operation"], &operation); err != nil {
		return nil, fmt.Errorf("_tmm-result.json is invalid")
	}
	var manifest Manifest
	fenced := requiresLinkageProducerFence(operation)
	hasBaseKeys := hasExactKeys(root, "version", "operation", "publication", "entries")
	hasFenceKeys := hasExactKeys(root, "version", "operation", "publication", "descriptor_version", "producer_version", "entries")
	if (!hasBaseKeys && !hasFenceKeys) || (!fenced && !hasBaseKeys) {
		return nil, fmt.Errorf("_tmm-result.json is invalid")
	}
	if err := json.Unmarshal(raw, &manifest); err != nil || manifest.Version != 1 ||
		(manifest.Publication != "tree" && manifest.Publication != "single" && manifest.Publication != "page-set") ||
		manifest.Entries == nil {
		return nil, fmt.Errorf("_tmm-result.json is invalid")
	}
	if hasFenceKeys &&
		(!fenced || manifest.DescriptorVersion != 2 || manifest.ProducerVersion != 2) {
		return nil, fmt.Errorf("_tmm-result.json producer fence is invalid")
	}
	var rawEntries []map[string]json.RawMessage
	if err := json.Unmarshal(root["entries"], &rawEntries); err != nil || rawEntries == nil {
		return nil, fmt.Errorf("_tmm-result.json entries are invalid")
	}
	if len(rawEntries) != len(manifest.Entries) {
		return nil, fmt.Errorf("_tmm-result.json entries are invalid")
	}
	declared := make(map[string]bool, len(manifest.Entries))
	for index, entry := range manifest.Entries {
		entryKeysValid := hasExactKeys(rawEntries[index], "path", "role", "size", "sha256")
		if manifest.Publication == "page-set" {
			entryKeysValid = hasExactKeys(rawEntries[index], "path", "role", "page", "size", "sha256") && entry.Page > 0
		} else if _, hasPage := rawEntries[index]["page"]; hasPage {
			var page *int
			entryKeysValid = hasExactKeys(rawEntries[index], "path", "role", "page", "size", "sha256") &&
				json.Unmarshal(rawEntries[index]["page"], &page) == nil && page == nil
		}
		if !entryKeysValid ||
			!validResultPath(entry.Path) || entry.Size < 0 ||
			(entry.Role != "artifact" && entry.Role != "primary" && entry.Role != "page") ||
			len(entry.SHA256) != sha256.Size*2 || strings.ToLower(entry.SHA256) != entry.SHA256 {
			return nil, fmt.Errorf("_tmm-result.json entry is invalid")
		}
		if _, err := hex.DecodeString(entry.SHA256); err != nil {
			return nil, fmt.Errorf("_tmm-result.json entry checksum is invalid")
		}
		if declared[entry.Path] {
			return nil, fmt.Errorf("_tmm-result.json contains duplicate member %s", entry.Path)
		}
		file, exists := files[entry.Path]
		if !exists {
			return nil, fmt.Errorf("manifest declares missing member %s", entry.Path)
		}
		if uint64(entry.Size) != file.UncompressedSize64 {
			return nil, fmt.Errorf("manifest member %s has the wrong size", entry.Path)
		}
		handle, err := file.Open()
		if err != nil {
			return nil, err
		}
		data, err := io.ReadAll(io.LimitReader(handle, maxResultBytes+1))
		handle.Close()
		if err != nil {
			return nil, err
		}
		if int64(len(data)) != entry.Size {
			return nil, fmt.Errorf("manifest member %s has the wrong size", entry.Path)
		}
		sum := sha256.Sum256(data)
		if hex.EncodeToString(sum[:]) != entry.SHA256 {
			return nil, fmt.Errorf("manifest member %s checksum mismatch", entry.Path)
		}
		declared[entry.Path] = true
	}
	delete(files, "_tmm-result.json")
	if len(declared) != len(files) {
		return nil, fmt.Errorf("undeclared result members")
	}
	for name := range files {
		if !declared[name] {
			return nil, fmt.Errorf("undeclared result member %s", name)
		}
	}
	return &manifest, nil
}

func validResultPath(path string) bool {
	if path == "" || path == "_tmm-result.json" || strings.HasPrefix(path, "/") ||
		strings.ContainsAny(path, `\`+"\x00") || (len(path) > 2 && path[1] == ':') {
		return false
	}
	for _, part := range strings.Split(path, "/") {
		if part == "" || part == "." || part == ".." {
			return false
		}
		for _, character := range part {
			if character <= 0x1f || character == 0x7f {
				return false
			}
		}
	}
	return true
}

func readAllLimited(rc interface{ Read([]byte) (int, error) }, limit int64) ([]byte, error) {
	var out bytes.Buffer
	buf := make([]byte, 32*1024)
	for int64(out.Len()) < limit {
		n, err := rc.Read(buf)
		if n > 0 {
			out.Write(buf[:n])
		}
		if err != nil {
			if err.Error() == "EOF" {
				return out.Bytes(), nil
			}
			type eofErr interface{ Unwrap() error }
			if e, ok := err.(eofErr); ok && e.Unwrap() != nil && e.Unwrap().Error() == "EOF" {
				return out.Bytes(), nil
			}
			return out.Bytes(), err
		}
	}
	return out.Bytes(), nil
}

// ReadPrimary validates and returns the sole member of a single-file result.
func ReadPrimary(zipData []byte, operation string) ([]byte, error) {
	manifest, err := ReadManifest(zipData)
	if err != nil {
		return nil, err
	}
	if manifest.Version != 1 || manifest.Operation != operation || manifest.Publication != "single" {
		return nil, fmt.Errorf("unexpected result manifest")
	}
	if len(manifest.Entries) != 1 || manifest.Entries[0].Role != "primary" {
		return nil, fmt.Errorf("result does not contain one primary member")
	}
	reader, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil {
		return nil, fmt.Errorf("result is not a valid ZIP: %w", err)
	}
	entry := manifest.Entries[0]
	for _, file := range reader.File {
		if file.Name != entry.Path {
			continue
		}
		handle, openErr := file.Open()
		if openErr != nil {
			return nil, openErr
		}
		data, readErr := readAllLimited(handle, 32<<20)
		handle.Close()
		if readErr != nil {
			return nil, readErr
		}
		if int64(len(data)) != entry.Size {
			return nil, fmt.Errorf("result member size mismatch")
		}
		if len(entry.SHA256) != sha256.Size*2 {
			return nil, fmt.Errorf("result member checksum is missing")
		}
		expected, decodeErr := hex.DecodeString(entry.SHA256)
		if decodeErr != nil {
			return nil, fmt.Errorf("result member checksum is invalid")
		}
		sum := sha256.Sum256(data)
		if !bytes.Equal(sum[:], expected) {
			return nil, fmt.Errorf("result member checksum mismatch")
		}
		return data, nil
	}
	return nil, fmt.Errorf("result member %s is missing", entry.Path)
}

// ReadPrimaryNamed validates a single-file result and requires its primary path.
func ReadPrimaryNamed(zipData []byte, operation, name string) ([]byte, error) {
	manifest, err := ReadManifest(zipData)
	if err != nil {
		return nil, err
	}
	if manifest.Operation != operation || manifest.Publication != "single" ||
		len(manifest.Entries) != 1 || manifest.Entries[0].Role != "primary" ||
		manifest.Entries[0].Path != name {
		return nil, fmt.Errorf("unexpected single-file result member")
	}
	return ReadPrimary(zipData, operation)
}

var planKeyIDPattern = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,64}$`)

// ReadPlan validates the paid KOMPAS result manifest and signed plan envelope.
// Signature authenticity is verified by the local KOMPAS Renderer, which owns
// the trusted server public key; this reader verifies the envelope and binding
// fields before handing the plan to that renderer.
func ReadPlan(zipData []byte, operation, runID, challenge string) ([]byte, error) {
	if operation != "linkage-cdw-scene-plan" && operation != "linkage-cdw-page-plan" {
		return nil, fmt.Errorf("unexpected KOMPAS operation")
	}
	manifest, err := ReadManifest(zipData)
	if err != nil {
		return nil, err
	}
	if manifest.Version != 1 || manifest.Operation != operation || manifest.Publication != "single" {
		return nil, fmt.Errorf("unexpected KOMPAS result manifest")
	}
	if len(manifest.Entries) != 1 || manifest.Entries[0].Role != "primary" || manifest.Entries[0].Path != "plan.json" {
		return nil, fmt.Errorf("KOMPAS result does not contain one plan member")
	}
	plan, err := readResultMember(zipData, manifest.Entries[0], 8<<20)
	if err != nil {
		return nil, err
	}
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(plan, &envelope); err != nil {
		return nil, fmt.Errorf("KOMPAS plan is not valid JSON: %w", err)
	}
	if !hasExactKeys(envelope, "format", "version", "algorithm", "key_id", "payload", "signature") {
		return nil, fmt.Errorf("KOMPAS plan envelope is invalid")
	}
	var format, algorithm, keyID, signature string
	var version int
	if json.Unmarshal(envelope["format"], &format) != nil ||
		json.Unmarshal(envelope["version"], &version) != nil ||
		json.Unmarshal(envelope["algorithm"], &algorithm) != nil ||
		json.Unmarshal(envelope["key_id"], &keyID) != nil ||
		json.Unmarshal(envelope["signature"], &signature) != nil ||
		format != "tmm-kompas-plan" || version != 1 || algorithm != "ed25519" ||
		!planKeyIDPattern.MatchString(keyID) {
		return nil, fmt.Errorf("KOMPAS plan envelope is invalid")
	}
	if len(signature) != 86 {
		return nil, fmt.Errorf("KOMPAS plan signature is invalid")
	}
	decodedSignature, err := base64.RawURLEncoding.Strict().DecodeString(signature)
	if err != nil || len(decodedSignature) != 64 {
		return nil, fmt.Errorf("KOMPAS plan signature is invalid")
	}
	var payload map[string]json.RawMessage
	if err := json.Unmarshal(envelope["payload"], &payload); err != nil {
		return nil, fmt.Errorf("KOMPAS plan payload is invalid")
	}
	if !hasExactKeys(payload, "operation", "job_id", "agent_challenge", "issued_at", "expires_at", "scene_sha256", "document", "operations") {
		return nil, fmt.Errorf("KOMPAS plan payload is invalid")
	}
	var payloadOperation, payloadJob, payloadChallenge, issuedAt, expiresAt, sceneSHA string
	var document map[string]json.RawMessage
	var operations []json.RawMessage
	if json.Unmarshal(payload["operation"], &payloadOperation) != nil ||
		json.Unmarshal(payload["job_id"], &payloadJob) != nil ||
		json.Unmarshal(payload["agent_challenge"], &payloadChallenge) != nil ||
		json.Unmarshal(payload["issued_at"], &issuedAt) != nil ||
		json.Unmarshal(payload["expires_at"], &expiresAt) != nil ||
		json.Unmarshal(payload["scene_sha256"], &sceneSHA) != nil ||
		json.Unmarshal(payload["document"], &document) != nil ||
		json.Unmarshal(payload["operations"], &operations) != nil ||
		payloadOperation != "kompas-plan" || payloadJob != runID || payloadChallenge != challenge ||
		issuedAt == "" || expiresAt == "" || len(sceneSHA) != 64 {
		return nil, fmt.Errorf("KOMPAS plan binding is invalid")
	}
	if _, err := hex.DecodeString(sceneSHA); err != nil {
		return nil, fmt.Errorf("KOMPAS plan binding is invalid")
	}
	return plan, nil
}

func hasExactKeys(values map[string]json.RawMessage, keys ...string) bool {
	if len(values) != len(keys) {
		return false
	}
	for _, key := range keys {
		if _, ok := values[key]; !ok {
			return false
		}
	}
	return true
}

func readResultMember(zipData []byte, entry struct {
	Path   string `json:"path"`
	Role   string `json:"role"`
	Page   int    `json:"page"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
}, limit int64) ([]byte, error) {
	reader, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil {
		return nil, fmt.Errorf("result is not a valid ZIP: %w", err)
	}
	for _, file := range reader.File {
		if file.Name != entry.Path {
			continue
		}
		handle, err := file.Open()
		if err != nil {
			return nil, err
		}
		data, readErr := io.ReadAll(io.LimitReader(handle, limit+1))
		handle.Close()
		if readErr != nil {
			return nil, readErr
		}
		if int64(len(data)) > limit || int64(len(data)) != entry.Size {
			return nil, fmt.Errorf("result member size mismatch")
		}
		if len(entry.SHA256) != sha256.Size*2 {
			return nil, fmt.Errorf("result member checksum is missing")
		}
		expected, decodeErr := hex.DecodeString(entry.SHA256)
		if decodeErr != nil {
			return nil, fmt.Errorf("result member checksum is invalid")
		}
		sum := sha256.Sum256(data)
		if !bytes.Equal(sum[:], expected) {
			return nil, fmt.Errorf("result member checksum mismatch")
		}
		return data, nil
	}
	return nil, fmt.Errorf("result member %s is missing", entry.Path)
}

// ReadMarkdownPreview validates the server-produced Markdown preview ZIP.
func ReadMarkdownPreview(zipData []byte, paperFormat string) error {
	const maxBytes = 20 << 20
	const maxEntries = 1025
	if len(zipData) > maxBytes {
		return fmt.Errorf("Markdown preview ZIP is too large")
	}
	reader, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil {
		return fmt.Errorf("Markdown preview ZIP is invalid: %w", err)
	}
	if len(reader.File) == 0 || len(reader.File) > maxEntries {
		return fmt.Errorf("Markdown preview ZIP members are invalid")
	}
	files := make(map[string][]byte, len(reader.File))
	var total int64
	for _, file := range reader.File {
		if _, exists := files[file.Name]; exists || !validPreviewPath(file.Name) {
			return fmt.Errorf("Markdown preview ZIP member path is invalid")
		}
		if file.FileInfo().IsDir() || file.FileInfo().Mode()&os.ModeSymlink != 0 ||
			file.UncompressedSize64 > maxBytes || file.CompressedSize64 > maxBytes ||
			(file.UncompressedSize64 > 0 && file.CompressedSize64 > 0 &&
				file.UncompressedSize64 > 200*file.CompressedSize64) {
			return fmt.Errorf("Markdown preview ZIP member is invalid")
		}
		total += int64(file.UncompressedSize64)
		if total > maxBytes {
			return fmt.Errorf("Markdown preview ZIP is too large")
		}
		handle, openErr := file.Open()
		if openErr != nil {
			return openErr
		}
		data, readErr := io.ReadAll(io.LimitReader(handle, maxBytes+1))
		handle.Close()
		if readErr != nil {
			return readErr
		}
		if len(data) > maxBytes || uint64(len(data)) != file.UncompressedSize64 {
			return fmt.Errorf("Markdown preview ZIP member size is invalid")
		}
		files[file.Name] = data
	}
	rawManifest, ok := files["_tmm-md-preview.json"]
	if !ok {
		return fmt.Errorf("Markdown preview manifest is missing")
	}
	var root map[string]json.RawMessage
	if err := json.Unmarshal(rawManifest, &root); err != nil ||
		!hasExactKeys(root, "version", "format", "documents", "entries") {
		return fmt.Errorf("Markdown preview manifest is invalid")
	}
	var version int
	var format string
	if json.Unmarshal(root["version"], &version) != nil || version != 2 ||
		json.Unmarshal(root["format"], &format) != nil || format != paperFormat {
		return fmt.Errorf("Markdown preview manifest is invalid")
	}
	var entries []map[string]json.RawMessage
	if err := json.Unmarshal(root["entries"], &entries); err != nil || entries == nil {
		return fmt.Errorf("Markdown preview manifest entries are invalid")
	}
	declared := make(map[string]string, len(entries))
	for _, entry := range entries {
		if !hasExactKeys(entry, "path", "role", "size", "sha256") {
			return fmt.Errorf("Markdown preview manifest entry is invalid")
		}
		var path, role, hash string
		var size int64
		if json.Unmarshal(entry["path"], &path) != nil || json.Unmarshal(entry["role"], &role) != nil ||
			json.Unmarshal(entry["size"], &size) != nil || json.Unmarshal(entry["sha256"], &hash) != nil ||
			!validPreviewPath(path) || path == "_tmm-md-preview.json" ||
			(role != "preview" && role != "scene") || size < 0 ||
			len(hash) != 64 || strings.ToLower(hash) != hash {
			return fmt.Errorf("Markdown preview manifest entry is invalid")
		}
		if _, duplicate := declared[path]; duplicate {
			return fmt.Errorf("Markdown preview manifest entry is duplicated")
		}
		data, present := files[path]
		if !present || int64(len(data)) != size {
			return fmt.Errorf("Markdown preview member is missing or has the wrong size")
		}
		digest := sha256.Sum256(data)
		if hex.EncodeToString(digest[:]) != hash {
			return fmt.Errorf("Markdown preview member hash is invalid")
		}
		if role == "preview" {
			if !strings.HasSuffix(path, ".svg") || !validSVG(data) {
				return fmt.Errorf("Markdown preview SVG is invalid")
			}
		} else if !strings.HasSuffix(path, ".scene.json") || !validScene(data) {
			return fmt.Errorf("Markdown preview scene is invalid")
		}
		declared[path] = role
	}
	if len(declared) != len(files)-1 {
		return fmt.Errorf("Markdown preview manifest entries are incomplete")
	}
	for path := range files {
		if path != "_tmm-md-preview.json" {
			if _, ok := declared[path]; !ok {
				return fmt.Errorf("Markdown preview manifest entries are incomplete")
			}
		}
	}
	var documents []map[string]json.RawMessage
	if err := json.Unmarshal(root["documents"], &documents); err != nil || documents == nil {
		return fmt.Errorf("Markdown preview documents are invalid")
	}
	documentPaths := map[string]bool{}
	references := map[string]int{}
	for _, document := range documents {
		if !hasKeys(document, "source_path", "title", "status", "pages") {
			return fmt.Errorf("Markdown preview document is invalid")
		}
		var sourcePath, title, status string
		if json.Unmarshal(document["source_path"], &sourcePath) != nil ||
			json.Unmarshal(document["title"], &title) != nil ||
			json.Unmarshal(document["status"], &status) != nil ||
			!validPreviewPath(sourcePath) || !strings.HasSuffix(sourcePath, ".md") ||
			documentPaths[sourcePath] || (status != "ready" && status != "error") {
			return fmt.Errorf("Markdown preview document is invalid")
		}
		documentPaths[sourcePath] = true
		if status == "error" {
			if !hasExactKeys(document, "source_path", "title", "status", "pages", "error") ||
				!validPreviewError(document["error"]) {
				return fmt.Errorf("Markdown preview document is invalid")
			}
		} else if !hasExactKeys(document, "source_path", "title", "status", "pages") {
			return fmt.Errorf("Markdown preview document is invalid")
		}
		var pages []map[string]json.RawMessage
		if err := json.Unmarshal(document["pages"], &pages); err != nil || pages == nil {
			return fmt.Errorf("Markdown preview pages are invalid")
		}
		indices := map[int]bool{}
		for _, page := range pages {
			if !hasKeys(page, "index", "status") {
				return fmt.Errorf("Markdown preview page is invalid")
			}
			var index int
			var pageStatus string
			if json.Unmarshal(page["index"], &index) != nil || json.Unmarshal(page["status"], &pageStatus) != nil ||
				index < 0 || indices[index] || (pageStatus != "ready" && pageStatus != "error") {
				return fmt.Errorf("Markdown preview page is invalid")
			}
			indices[index] = true
			if pageStatus == "ready" {
				if !hasExactKeys(page, "index", "status", "preview_path", "scene_path") {
					return fmt.Errorf("Markdown preview page is invalid")
				}
				var previewPath, scenePath string
				if json.Unmarshal(page["preview_path"], &previewPath) != nil ||
					json.Unmarshal(page["scene_path"], &scenePath) != nil ||
					previewPath == scenePath || declared[previewPath] != "preview" ||
					declared[scenePath] != "scene" {
					return fmt.Errorf("Markdown preview page is invalid")
				}
				references[previewPath]++
				references[scenePath]++
			} else if !hasExactKeys(page, "index", "status", "error") || !validPreviewError(page["error"]) {
				return fmt.Errorf("Markdown preview page is invalid")
			}
		}
	}
	if len(references) != len(declared) {
		return fmt.Errorf("Markdown preview pages are not fully indexed")
	}
	for path := range declared {
		if references[path] != 1 {
			return fmt.Errorf("Markdown preview pages are not fully indexed")
		}
	}
	return nil
}

func hasKeys(values map[string]json.RawMessage, keys ...string) bool {
	for _, key := range keys {
		if _, ok := values[key]; !ok {
			return false
		}
	}
	return true
}

func validPreviewError(raw json.RawMessage) bool {
	var value map[string]json.RawMessage
	if json.Unmarshal(raw, &value) != nil || value == nil ||
		!hasKeys(value, "code", "message", "field", "line", "column", "stage") {
		return false
	}
	var code, message, stage string
	if json.Unmarshal(value["code"], &code) != nil || code == "" ||
		json.Unmarshal(value["message"], &message) != nil || message == "" ||
		json.Unmarshal(value["stage"], &stage) != nil || stage == "" {
		return false
	}
	for key := range value {
		if key != "code" && key != "message" && key != "field" && key != "line" &&
			key != "column" && key != "stage" && key != "issues" && key != "plotId" {
			return false
		}
	}
	if code != "annotation_layout_failed" {
		if _, ok := value["plotId"]; ok {
			return false
		}
	}
	if field := value["field"]; string(field) != "null" {
		var text string
		if json.Unmarshal(field, &text) != nil {
			return false
		}
	}
	for _, key := range []string{"line", "column"} {
		rawNumber := value[key]
		if string(rawNumber) == "null" {
			continue
		}
		var number int
		if json.Unmarshal(rawNumber, &number) != nil || number < 1 {
			return false
		}
	}
	if plotID, ok := value["plotId"]; ok {
		var text string
		if json.Unmarshal(plotID, &text) != nil || text == "" || len(text) > 64 || !validPreviewPath(text) {
			return false
		}
	}
	if issues, ok := value["issues"]; ok && string(issues) != "null" {
		var list []json.RawMessage
		if json.Unmarshal(issues, &list) != nil || list == nil || len(list) > 8 {
			return false
		}
	}
	return true
}

func validPreviewPath(path string) bool {
	if path == "" || strings.HasPrefix(path, "/") || strings.ContainsAny(path, "\\\x00") ||
		(len(path) > 2 && path[1] == ':') {
		return false
	}
	for _, segment := range strings.Split(path, "/") {
		if segment == "" || segment == "." || segment == ".." {
			return false
		}
		for _, character := range segment {
			if character < 0x20 || character == 0x7f {
				return false
			}
		}
	}
	return true
}

func validSVG(data []byte) bool {
	decoder := xml.NewDecoder(bytes.NewReader(data))
	for {
		token, err := decoder.Token()
		if err != nil {
			return false
		}
		if start, ok := token.(xml.StartElement); ok {
			return start.Name.Local == "svg" && start.Name.Space == "http://www.w3.org/2000/svg"
		}
	}
}

func validScene(data []byte) bool {
	var scene map[string]json.RawMessage
	if json.Unmarshal(data, &scene) != nil {
		return false
	}
	var format, units string
	var version int
	return json.Unmarshal(scene["format"], &format) == nil && format == "tmm-scene" &&
		json.Unmarshal(scene["version"], &version) == nil && version == 2 &&
		json.Unmarshal(scene["units"], &units) == nil && units == "mm"
}

// NewUUIDv4 returns a random RFC 4122 version 4 UUID string.
func NewUUIDv4() (string, error) {
	return newUUIDv4()
}
