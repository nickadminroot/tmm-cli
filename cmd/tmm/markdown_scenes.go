package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"unicode"
)

// collectMarkdownScenes reads only explicit, visible scene bindings. Missing
// files are omitted so the server can use its generated catalog; existing
// files must be JSON objects and remain relative to the Markdown directory.
func collectMarkdownScenes(documentPath string, document []byte) ([]byte, error) {
	references := markdownSceneReferences(string(document))
	if len(references) == 0 {
		return nil, nil
	}
	base, err := filepath.Abs(filepath.Dir(documentPath))
	if err != nil {
		return nil, fmt.Errorf("resolve Markdown directory: %w", err)
	}
	base = filepath.Clean(base)
	scenes := make(map[string]json.RawMessage, len(references))
	for _, reference := range references {
		name, err := canonicalSceneReference(reference)
		if err != nil {
			return nil, err
		}
		if _, exists := scenes[name]; exists {
			continue
		}
		localPath, err := localScenePath(base, name)
		if err != nil {
			return nil, fmt.Errorf("scene %q: %w", reference, err)
		}
		if err := ensureLocalScenePath(base, localPath); err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			return nil, fmt.Errorf("scene %q: %w", reference, err)
		}
		info, err := os.Stat(localPath)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			return nil, fmt.Errorf("stat scene %q: %w", reference, err)
		}
		if !info.Mode().IsRegular() {
			return nil, fmt.Errorf("scene %q is not a regular file", reference)
		}
		data, err := os.ReadFile(localPath)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			return nil, fmt.Errorf("read scene %q: %w", reference, err)
		}
		if err := validateSceneObject(data); err != nil {
			return nil, fmt.Errorf("scene %q: %w", reference, err)
		}
		scenes[name] = json.RawMessage(data)
	}
	if len(scenes) == 0 {
		return nil, nil
	}
	payload, err := json.Marshal(scenes)
	if err != nil {
		return nil, fmt.Errorf("encode scenes payload: %w", err)
	}
	return payload, nil
}

func canonicalSceneReference(reference string) (string, error) {
	if reference == "" || strings.TrimSpace(reference) != reference ||
		strings.ContainsAny(reference, "\\?#") || strings.HasPrefix(reference, "/") ||
		(len(reference) > 1 && reference[1] == ':') ||
		strings.Contains(strings.SplitN(reference, "/", 2)[0], ":") {
		return "", fmt.Errorf("scene reference must be a safe relative path: %s", reference)
	}
	for _, r := range reference {
		if r == 0 || unicode.IsControl(r) || unicode.IsSpace(r) {
			return "", fmt.Errorf("scene reference must be a safe relative path: %s", reference)
		}
	}
	for _, part := range strings.Split(reference, "/") {
		if part == "" || part == "." || part == ".." {
			return "", fmt.Errorf("scene reference contains an unsafe path: %s", reference)
		}
	}
	if !strings.HasSuffix(reference, ".scene.json") && !strings.HasSuffix(reference, ".render.json") {
		return "", fmt.Errorf("scene reference must end in .scene.json or .render.json: %s", reference)
	}
	return reference, nil
}

func localScenePath(base, reference string) (string, error) {
	candidate := filepath.Clean(filepath.Join(base, filepath.FromSlash(reference)))
	relative, err := filepath.Rel(base, candidate)
	if err != nil {
		return "", err
	}
	if relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || filepath.IsAbs(relative) {
		return "", fmt.Errorf("scene path escapes the Markdown directory")
	}
	return candidate, nil
}

func ensureLocalScenePath(base, candidate string) error {
	realBase, err := filepath.EvalSymlinks(base)
	if err != nil {
		return fmt.Errorf("resolve Markdown directory: %w", err)
	}
	realCandidate, err := filepath.EvalSymlinks(candidate)
	if err != nil {
		return fmt.Errorf("resolve scene path: %w", err)
	}
	relative, err := filepath.Rel(realBase, realCandidate)
	if err != nil {
		return err
	}
	if relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || filepath.IsAbs(relative) {
		return fmt.Errorf("scene path escapes the Markdown workspace")
	}
	return nil
}

func validateSceneObject(data []byte) error {
	var object map[string]json.RawMessage
	if err := json.Unmarshal(data, &object); err != nil || object == nil {
		return fmt.Errorf("scene file must contain a JSON object")
	}
	return nil
}

// markdownSceneReferences extracts the four known scene directive names.
// Markdown fences and inline-code spans are masked so examples do not upload
// files. Directive grammar remains owned by the server's Markdown compiler.
func markdownSceneReferences(document string) []string {
	var references []string
	var fence byte
	fenceLength := 0
	for _, rawLine := range strings.SplitAfter(document, "\n") {
		line := strings.TrimSuffix(strings.TrimSuffix(rawLine, "\n"), "\r")
		trimmed := strings.TrimLeft(line, " \t")
		if fence != 0 {
			if markdownFenceClose(trimmed, fence, fenceLength) {
				fence, fenceLength = 0, 0
			}
			continue
		}
		if marker, length, ok := markdownFenceStart(trimmed); ok {
			fence, fenceLength = marker, length
			continue
		}
		masked := maskInlineCode(line)
		for offset := 0; offset < len(masked); {
			relative := strings.Index(masked[offset:], "{{tmm-")
			if relative < 0 {
				break
			}
			start := offset + relative
			bodyStart := start + 2
			commandEnd := bodyStart
			for commandEnd < len(masked) && masked[commandEnd] != ' ' && masked[commandEnd] != '}' {
				commandEnd++
			}
			command := masked[bodyStart:commandEnd]
			key := "scene"
			if command == "tmm-scene" {
				key = "name"
			} else if command != "tmm-scale" && command != "tmm-segment" && command != "tmm-lever" {
				close := strings.Index(masked[bodyStart:], "}}")
				if close < 0 {
					break
				}
				offset = bodyStart + close + 2
				continue
			}
			close := strings.Index(masked[bodyStart:], "}}")
			if close < 0 {
				break
			}
			body := masked[bodyStart : bodyStart+close]
			if value, ok := directiveAttribute(body, key); ok {
				references = append(references, value)
			}
			offset = bodyStart + close + 2
		}
	}
	return references
}

func directiveAttribute(body, key string) (string, bool) {
	needle := key + "=\""
	for offset := 0; ; {
		relative := strings.Index(body[offset:], needle)
		if relative < 0 {
			return "", false
		}
		start := offset + relative
		if start > 0 && body[start-1] != ' ' {
			offset = start + len(needle)
			continue
		}
		valueStart := start + len(needle)
		end := strings.IndexByte(body[valueStart:], '"')
		if end < 0 || end == 0 {
			return "", false
		}
		return body[valueStart : valueStart+end], true
	}
}

func markdownFenceStart(line string) (byte, int, bool) {
	if len(line) < 3 || (line[0] != '`' && line[0] != '~') {
		return 0, 0, false
	}
	marker, count := line[0], 0
	for count < len(line) && line[count] == marker {
		count++
	}
	return marker, count, count >= 3
}

func markdownFenceClose(line string, marker byte, minimum int) bool {
	if len(line) < minimum || line[0] != marker {
		return false
	}
	count := 0
	for count < len(line) && line[count] == marker {
		count++
	}
	return count >= minimum && strings.TrimSpace(line[count:]) == ""
}

func maskInlineCode(line string) string {
	masked := []byte(line)
	for index := 0; index < len(line); {
		if line[index] != '`' {
			index++
			continue
		}
		start := index
		for index < len(line) && line[index] == '`' {
			index++
		}
		length := index - start
		end := strings.Index(line[index:], strings.Repeat("`", length))
		if end < 0 {
			for cursor := start; cursor < len(masked); cursor++ {
				masked[cursor] = ' '
			}
			break
		}
		end += index
		for cursor := start; cursor < end+length; cursor++ {
			masked[cursor] = ' '
		}
		index = end + length
	}
	return string(masked)
}
