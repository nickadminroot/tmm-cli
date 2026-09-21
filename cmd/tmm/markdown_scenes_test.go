package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCollectMarkdownScenesUsesVisibleReferencesAndRawKeys(t *testing.T) {
	root := t.TempDir()
	documentPath := filepath.Join(root, "docs", "page.md")
	if err := os.MkdirAll(filepath.Join(root, "docs", "sub"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "docs", "velocity.scene.json"), []byte(`{"kind":"velocity-plan"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "docs", "sub", "force.render.json"), []byte(`{"kind":"force-plan"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	markdown := strings.Join([]string{
		"# Sheet",
		"{{tmm-scene name=\"velocity.scene.json\"}}",
		"Force: {{tmm-segment scene=\"sub/force.render.json\" id=\"length\"}}",
		"Scale: {{tmm-scale scene=\"velocity.scene.json\"}}",
		"```md",
		"{{tmm-scene name=\"missing.scene.json\"}}",
		"```md",
		"{{tmm-scene name=\"missing-language.scene.json\"}}",
		"```",
		"Inline `{{tmm-scene name=\"missing-inline.scene.json\"}}` example.",
	}, "\n")
	payload, err := collectMarkdownScenes(documentPath, []byte(markdown))
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]json.RawMessage
	if err := json.Unmarshal(payload, &got); err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 {
		t.Fatalf("scene keys = %#v, want two raw directive keys", got)
	}
	if string(got["velocity.scene.json"]) != `{"kind":"velocity-plan"}` {
		t.Fatalf("velocity scene = %s", got["velocity.scene.json"])
	}
	if string(got["sub/force.render.json"]) != `{"kind":"force-plan"}` {
		t.Fatalf("force scene = %s", got["sub/force.render.json"])
	}
}

func TestCollectMarkdownScenesLeavesMissingFilesForGeneratedFallback(t *testing.T) {
	documentPath := filepath.Join(t.TempDir(), "page.md")
	payload, err := collectMarkdownScenes(documentPath, []byte(`{{tmm-scale scene="generated.scene.json"}}`))
	if err != nil {
		t.Fatal(err)
	}
	if payload != nil {
		t.Fatalf("missing scene payload = %s, want nil fallback", payload)
	}
}

func TestCollectMarkdownScenesRejectsInvalidExistingFilesAndReferences(t *testing.T) {
	root := t.TempDir()
	documentPath := filepath.Join(root, "page.md")
	if err := os.WriteFile(filepath.Join(root, "bad.scene.json"), []byte(`[]`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := collectMarkdownScenes(documentPath, []byte(`{{tmm-scene name="bad.scene.json"}}`)); err == nil || !strings.Contains(err.Error(), "JSON object") {
		t.Fatalf("invalid object error = %v", err)
	}
	for _, reference := range []string{
		"../escape.scene.json",
		"/absolute.scene.json",
		"https://example.test/scene.scene.json",
		"unsafe.txt",
	} {
		_, err := collectMarkdownScenes(documentPath, []byte(`{{tmm-scale scene="`+reference+`"}}`))
		if err == nil {
			t.Fatalf("reference %q accepted", reference)
		}
	}
}

func TestCollectMarkdownScenesReportsUnreadablePresentPath(t *testing.T) {
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "directory.scene.json"), 0o700); err != nil {
		t.Fatal(err)
	}
	_, err := collectMarkdownScenes(filepath.Join(root, "page.md"), []byte(`{{tmm-scene name="directory.scene.json"}}`))
	if err == nil || !strings.Contains(err.Error(), "regular file") {
		t.Fatalf("directory scene error = %v", err)
	}
}

func TestCollectMarkdownScenesRejectsSymlinkOutsideWorkspace(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	outsideScene := filepath.Join(outside, "outside.scene.json")
	if err := os.WriteFile(outsideScene, []byte(`{"kind":"outside"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outsideScene, filepath.Join(root, "link.scene.json")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}
	_, err := collectMarkdownScenes(filepath.Join(root, "page.md"), []byte(`{{tmm-scene name="link.scene.json"}}`))
	if err == nil || !strings.Contains(err.Error(), "escapes") {
		t.Fatalf("outside symlink error = %v", err)
	}
}
