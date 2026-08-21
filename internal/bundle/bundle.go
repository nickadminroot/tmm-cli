package bundle

import (
	"archive/zip"
	"bytes"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
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
func SingleFile(inputPath string, op string) (*Bundle, error) {
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
	name := filepath.Base(inputPath)
	logical := "workspace/" + name
	buf := &bytes.Buffer{}
	w := zip.NewWriter(buf)
	fw, err := w.Create(logical)
	if err != nil {
		return nil, err
	}
	if _, werr := fw.Write(data); werr != nil {
		return nil, err
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	return &Bundle{Data: buf.Bytes(), Entrypoint: logical}, nil
}

// BundleMarkdown stages a Markdown source plus every scene it references into
// an in-memory workspace. Scene references follow the owner grammar: a
// standalone paragraph whose sole link text is `scene` and whose
// percent-decoded destination ends in .scene.json.
func BundleMarkdown(sourcePath, format string) (env map[string]any, b *Bundle, err error) {
	data, serr := os.ReadFile(sourcePath)
	if serr != nil {
		return nil, nil, &UsageError{msg: serr.Error()}
	}
	source := string(data)

	refs, maxUp, rerr := discoverSceneRefs(source)
	if rerr != nil {
		return nil, nil, rerr
	}
	if maxUp < 0 {
		maxUp = 0
	}
	synthDir := "workspace"
	for i := 0; i < maxUp; i++ {
		synthDir = synthDir + fmt.Sprintf("/_up%d", i+1)
	}
	logicalSource := synthDir + "/" + filepath.Base(sourcePath)

	sceneDocs := map[string]string{}
	baseDir := filepath.Dir(sourcePath)
	for _, ref := range refs {
		hostPath := filepath.Join(baseDir, filepath.FromSlash(ref))
		hostPath = filepath.Clean(hostPath)
		st, serr := os.Stat(hostPath)
		if serr != nil || st.IsDir() {
			return nil, nil, &UsageError{msg: fmt.Sprintf("scene reference %q: file not found", ref)}
		}
		text, rerr2 := os.ReadFile(hostPath)
		if rerr2 != nil {
			return nil, nil, &UsageError{msg: rerr2.Error()}
		}
		logical, lerr := resolveLogical(synthDir, ref)
		if lerr != nil {
			return nil, nil, &UsageError{msg: lerr.Error()}
		}
		if prev, dup := sceneDocs[logical]; dup && prev != string(text) {
			return nil, nil, &UsageError{msg: fmt.Sprintf("two different local files map to %s", logical)}
		}
		sceneDocs[logical] = string(text)
	}

	files := map[string][]byte{
		logicalSource: data,
	}
	for logical, text := range sceneDocs {
		files[logical] = []byte(text)
	}

	zdata, zerr := zipBytes(files)
	if zerr != nil {
		return nil, nil, zerr
	}
	envMap := map[string]any{
		"version":    1,
		"operation":  "md",
		"entrypoint": logicalSource,
		"options":    map[string]any{"format": format},
	}
	return envMap, &Bundle{Data: zdata, Entrypoint: logicalSource}, nil
}

// resolveLogical applies `..` hops to synthDir exactly like the server resolver.
func resolveLogical(synthDir, reference string) (string, error) {
	segments := strings.Split(synthDir, "/")
	for _, seg := range strings.Split(reference, "/") {
		switch seg {
		case "..":
			if len(segments) <= 1 {
				return "", fmt.Errorf("reference %q escapes the submitted workspace", reference)
			}
			segments = segments[:len(segments)-1]
		case ".", "":
			continue
		default:
			segments = append(segments, seg)
		}
	}
	out := strings.Join(segments, "/")
	if !strings.HasPrefix(out, "workspace/") {
		return "", fmt.Errorf("reference %q escapes the submitted workspace", reference)
	}
	return out, nil
}

func zipBytes(files map[string][]byte) ([]byte, error) {
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sortStrings(names)
	buf := &bytes.Buffer{}
	w := zip.NewWriter(buf)
	for _, name := range names {
		if len(files[name]) > 25<<20 {
			return nil, &UsageError{msg: fmt.Sprintf("%s exceeds the 25 MiB per-file limit", name)}
		}
		fw, cerr := w.Create(name)
		if cerr != nil {
			return nil, cerr
		}
		if _, werr := fw.Write(files[name]); werr != nil {
			return nil, werr
		}
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	total := buf.Len()
	if total > 25<<20 {
		return nil, &UsageError{msg: fmt.Sprintf("bundle is %d bytes; limit is 25 MiB", total)}
	}
	return buf.Bytes(), nil
}

func sortStrings(list []string) {
	for i := 1; i < len(list); i++ {
		for j := i; j > 0 && list[j] < list[j-1]; j-- {
			list[j], list[j-1] = list[j-1], list[j]
		}
	}
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
	Version     int    `json:"version"`
	Operation   string `json:"operation"`
	Publication string `json:"publication"`
	Entries     []struct {
		Path string `json:"path"`
		Role string `json:"role"`
		Page int    `json:"page"`
		Size int64  `json:"size"`
	} `json:"entries"`
}

func ReadManifest(zipData []byte) (*Manifest, error) {
	reader, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil {
		return nil, fmt.Errorf("result is not a valid ZIP: %w", err)
	}
	declared := map[string]bool{}
	var manifest *Manifest
	for _, f := range reader.File {
		if f.Name == "_tmm-result.json" {
			rc, oerr := f.Open()
			if oerr != nil {
				return nil, oerr
			}
			raw, _ := readAllLimited(rc, 1<<20)
			rc.Close()
			manifest = &Manifest{}
			if jerr := json.Unmarshal(raw, manifest); jerr != nil {
				return nil, fmt.Errorf("_tmm-result.json: %w", jerr)
			}
			continue
		}
		declared[f.Name] = true
	}
	if manifest == nil {
		return nil, fmt.Errorf("result ZIP has no _tmm-result.json")
	}
	for _, entry := range manifest.Entries {
		if !declared[entry.Path] {
			return nil, fmt.Errorf("manifest declares missing member %s", entry.Path)
		}
		delete(declared, entry.Path)
	}
	if len(declared) > 0 {
		extra := make([]string, 0, len(declared))
		for name := range declared {
			extra = append(extra, name)
		}
		return nil, fmt.Errorf("undeclared result members: %v", extra)
	}
	return manifest, nil
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

// NewUUIDv4 returns a random RFC 4122 version 4 UUID string.
func NewUUIDv4() (string, error) {
	return newUUIDv4()
}
