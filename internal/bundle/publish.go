package bundle

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// discoverSceneRefs implements the tmm-md scene-reference grammar: a
// standalone paragraph whose sole link text is `scene` and whose
// percent-decoded destination ends in .scene.json. Returns references in
// source order (deduplicated) and the maximum `..` depth across them.
func discoverSceneRefs(source string) ([]string, int, error) {
	paraRe := regexp.MustCompile(`(?m)^\[scene\]\(([^)]+)\)\s*$`)
	refRe := regexp.MustCompile(`\.scene\.json$`)
	hexVal := func(c byte) int {
		switch {
		case c >= '0' && c <= '9':
			return int(c - '0')
		case c >= 'a' && c <= 'f':
			return int(c-'a') + 10
		case c >= 'A' && c <= 'F':
			return int(c-'A') + 10
		}
		return -1
	}
	pctDecode := func(s string) string {
		out := s
		for {
			i := indexOfPercent(out)
			if i < 0 || i+2 >= len(out) {
				return out
			}
			hi := hexVal(out[i+1])
			lo := hexVal(out[i+2])
			if hi < 0 || lo < 0 {
				return out
			}
			out = out[:i] + string(rune(hi<<4|lo)) + out[i+3:]
		}
	}

	var refs []string
	seen := map[string]bool{}
	maxUp := 0
	for _, m := range paraRe.FindAllStringSubmatch(source, -1) {
		dest := pctDecode(m[1])
		if !refRe.MatchString(dest) {
			continue
		}
		if dest == "" || strings.ContainsAny(dest, " \t") {
			return nil, 0, &UsageError{msg: fmt.Sprintf("invalid scene reference %q", m[1])}
		}
		if strings.HasPrefix(dest, "/") || regexp.MustCompile(`^[A-Za-z]:`).MatchString(dest) {
			return nil, 0, &UsageError{msg: fmt.Sprintf("absolute scene reference %q must be relative", m[1])}
		}
		up := 0
		for _, seg := range strings.Split(dest, "/") {
			if seg == ".." {
				up++
			}
		}
		if up > maxUp {
			maxUp = up
		}
		if !seen[dest] {
			seen[dest] = true
			refs = append(refs, dest)
		}
	}
	return refs, maxUp, nil
}

// Publication writes a result ZIP to local disk per the publication contract.
type Publisher struct{}

// publishTree atomically replaces every returned relative file under outputDir.
func (Publisher) PublishTree(zipData []byte, manifest *Manifest, outputDir string) error {
	reader, err := openZip(zipData)
	if err != nil {
		return err
	}
	if mkerr := os.MkdirAll(outputDir, 0o755); mkerr != nil {
		return mkerr
	}
	for _, entry := range manifest.Entries {
		f, ferr := reader.Open(entry.Path)
		if ferr != nil {
			return fmt.Errorf("result member %s: %w", entry.Path, ferr)
		}
		data, rerr := io.ReadAll(f)
		f.Close()
		if rerr != nil {
			return rerr
		}
		target := filepath.Join(outputDir, filepath.FromSlash(entry.Path))
		if !isUnder(outputDir, target) {
			return fmt.Errorf("member %s escapes the output directory", entry.Path)
		}
		if mkerr := os.MkdirAll(filepath.Dir(target), 0o755); mkerr != nil {
			return mkerr
		}
		if werr := atomicWrite(target, data); werr != nil {
			return werr
		}
		fmt.Println(target)
	}
	return nil
}

// publishSingle writes one member to the exact --output path.
func (Publisher) PublishSingle(zipData []byte, manifest *Manifest, outputPath string) error {
	if len(manifest.Entries) == 0 {
		return fmt.Errorf("empty result")
	}
	reader, err := openZip(zipData)
	if err != nil {
		return err
	}
	name := manifest.Entries[0].Path
	f, oerr := reader.Open(name)
	if oerr != nil {
		return oerr
	}
	data, rerr := io.ReadAll(f)
	f.Close()
	if rerr != nil {
		return rerr
	}
	dir := filepath.Dir(outputPath)
	if mkerr := os.MkdirAll(dir, 0o755); mkerr != nil {
		return mkerr
	}
	if werr := atomicWrite(outputPath, data); werr != nil {
		return werr
	}
	fmt.Println(outputPath)
	return nil
}

// publishPageSet writes page-N files and removes stale siblings only after
// all new pages are durable.
func (Publisher) PublishPageSet(zipData []byte, manifest *Manifest, outputPath string) error {
	ext := filepath.Ext(outputPath)
	stem := outputPath[:len(outputPath)-len(ext)]
	reader, err := openZip(zipData)
	if err != nil {
		return err
	}
	written := make([]string, 0, len(manifest.Entries))
	for _, entry := range manifest.Entries {
		f, oerr := reader.Open(entry.Path)
		if oerr != nil {
			return oerr
		}
		data, rerr := io.ReadAll(f)
		f.Close()
		if rerr != nil {
			return rerr
		}
		target := fmt.Sprintf("%s.page-%d%s", stem, entry.Page, ext)
		if werr := atomicWrite(target, data); werr != nil {
			return werr
		}
		written = append(written, target)
	}
	// Remove stale numbered siblings beyond the new set.
	for index := len(written) + 1; ; index++ {
		stale := fmt.Sprintf("%s.page-%d%s", stem, index, ext)
		if _, serr := os.Stat(stale); serr != nil {
			break
		}
		os.Remove(stale)
	}
	for _, path := range written {
		fmt.Println(path)
	}
	return nil
}

func openZip(zipData []byte) (*zipReader, error) {
	return newZipReader(zipData)
}

func isUnder(base, target string) bool {
	rel, err := filepath.Rel(base, target)
	if err != nil {
		return false
	}
	return rel != ".." && len(rel) > 0 && rel[:2] != ".."
}

func indexOfPercent(s string) int {
	for i := 0; i < len(s); i++ {
		if s[i] == '%' {
			return i
		}
	}
	return -1
}
