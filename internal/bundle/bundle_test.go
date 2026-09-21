package bundle

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func makeResultZip(t *testing.T, operation string, plan []byte) []byte {
	t.Helper()
	sum := sha256.Sum256(plan)
	manifest := map[string]any{
		"version":            1,
		"operation":          operation,
		"publication":        "single",
		"descriptor_version": 2,
		"producer_version":   2,
		"entries": []map[string]any{{
			"path":   "plan.json",
			"role":   "primary",
			"page":   nil,
			"size":   len(plan),
			"sha256": hex.EncodeToString(sum[:]),
		}},
	}
	manifestJSON, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	return makeZip(t, map[string][]byte{
		"plan.json":        plan,
		"_tmm-result.json": manifestJSON,
	})
}

func makeZip(t *testing.T, files map[string][]byte) []byte {
	t.Helper()
	var buffer bytes.Buffer
	archive := zip.NewWriter(&buffer)
	for name, data := range files {
		writer, err := archive.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := writer.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err := archive.Close(); err != nil {
		t.Fatal(err)
	}
	return buffer.Bytes()
}

func makeNamedResultZip(t *testing.T, operation, path string, data []byte) []byte {
	t.Helper()
	sum := sha256.Sum256(data)
	manifestJSON := mustJSON(t, map[string]any{
		"version":            1,
		"operation":          operation,
		"publication":        "single",
		"descriptor_version": 2,
		"producer_version":   2,
		"entries": []map[string]any{{
			"path": path, "role": "primary", "size": len(data), "sha256": hex.EncodeToString(sum[:]),
		}},
	})
	return makeZip(t, map[string][]byte{
		path:               data,
		"_tmm-result.json": manifestJSON,
	})
}

func validPlan(t *testing.T, runID, challenge string) []byte {
	t.Helper()
	return mustJSON(t, map[string]any{
		"format":    "tmm-kompas-plan",
		"version":   1,
		"algorithm": "ed25519",
		"key_id":    "default",
		"payload": map[string]any{
			"operation":       "kompas-plan",
			"job_id":          runID,
			"agent_challenge": challenge,
			"issued_at":       "2025-01-01T00:00:00Z",
			"expires_at":      "2025-01-01T00:05:00Z",
			"scene_sha256":    "0000000000000000000000000000000000000000000000000000000000000000",
			"document":        map[string]any{"kind": "part"},
			"operations":      []any{},
		},
		"signature": base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{'s'}, 64)),
	})
}

func mustJSON(t *testing.T, value any) []byte {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestReadPlanVerifiesPaidManifestAndBinding(t *testing.T) {
	runID := "11111111-1111-4111-8111-111111111111"
	challenge := base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{'c'}, 32))
	plan := validPlan(t, runID, challenge)
	result := makeResultZip(t, "linkage-cdw-scene-plan", plan)
	data, err := ReadPlan(result, "linkage-cdw-scene-plan", runID, challenge)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(data, plan) {
		t.Fatalf("plan = %q", data)
	}
}

func TestReadPublicPlanVerifiesOperationAndChallenge(t *testing.T) {
	challenge := base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{'c'}, 32))
	plan := validPlan(t, "11111111-1111-4111-8111-111111111111", challenge)
	result := makeResultZip(t, "cdw-scene-plan", plan)
	data, err := ReadPublicPlan(result, []string{"cdw-scene-plan", "cdw-render-plan"}, challenge)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(data, plan) {
		t.Fatalf("plan = %q", data)
	}
	if _, err := ReadPublicPlan(result, []string{"cdw-render-plan"}, challenge); err == nil {
		t.Fatal("ReadPublicPlan accepted an unexpected operation")
	}
	if _, err := ReadPublicPlan(result, []string{"cdw-scene-plan"}, strings.Repeat("x", 43)); err == nil {
		t.Fatal("ReadPublicPlan accepted a mismatched challenge")
	}
}

func TestReadPublicPlanRejectsMalformedPayload(t *testing.T) {
	challenge := base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{'c'}, 32))
	cases := map[string]func(map[string]any){
		"missing operations": func(payload map[string]any) {
			delete(payload, "operations")
		},
		"non-v4 job id": func(payload map[string]any) {
			payload["job_id"] = "11111111-1111-3111-8111-111111111111"
		},
		"expired interval": func(payload map[string]any) {
			payload["expires_at"] = "2024-12-31T23:59:00Z"
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			var planObject map[string]any
			if err := json.Unmarshal(validPlan(t, "11111111-1111-4111-8111-111111111111", challenge), &planObject); err != nil {
				t.Fatal(err)
			}
			payload := planObject["payload"].(map[string]any)
			mutate(payload)
			result := makeResultZip(t, "cdw-scene-plan", mustJSON(t, planObject))
			if _, err := ReadPublicPlan(result, []string{"cdw-scene-plan"}, challenge); err == nil {
				t.Fatal("ReadPublicPlan accepted malformed payload")
			}
		})
	}
}

func TestReadPrimaryNamedRequiresExpectedPath(t *testing.T) {
	xmcd := []byte("xmcd-bytes")
	result := makeNamedResultZip(t, "linkage-xmcd", "worksheet.xmcd", xmcd)
	if got, err := ReadPrimaryNamed(result, "linkage-xmcd", "worksheet.xmcd"); err != nil || !bytes.Equal(got, xmcd) {
		t.Fatalf("ReadPrimaryNamed = %q, %v", got, err)
	}
	if _, err := ReadPrimaryNamed(result, "linkage-xmcd", "plan.json"); err == nil {
		t.Fatal("ReadPrimaryNamed accepted an unexpected primary path")
	}
}

func TestReadPlanRejectsInvalidSignatureAndChallenge(t *testing.T) {
	runID := "11111111-1111-4111-8111-111111111111"
	challenge := base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{'c'}, 32))
	plan := validPlan(t, runID, challenge)
	var envelope map[string]any
	if err := json.Unmarshal(plan, &envelope); err != nil {
		t.Fatal(err)
	}
	envelope["signature"] = "bad"
	badSignature := makeResultZip(t, "linkage-cdw-page-plan", mustJSON(t, envelope))
	if _, err := ReadPlan(badSignature, "linkage-cdw-page-plan", runID, challenge); err == nil {
		t.Fatal("ReadPlan accepted an invalid signature")
	}
	wrongChallenge := makeResultZip(t, "linkage-cdw-page-plan", validPlan(t, runID, strings.Repeat("x", 43)))
	if _, err := ReadPlan(wrongChallenge, "linkage-cdw-page-plan", runID, challenge); err == nil {
		t.Fatal("ReadPlan accepted a mismatched challenge")
	}
}

func TestReadPlanRejectsMissingChecksum(t *testing.T) {
	runID := "11111111-1111-4111-8111-111111111111"
	challenge := base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{'c'}, 32))
	plan := validPlan(t, runID, challenge)
	manifest := map[string]any{
		"version":            1,
		"operation":          "linkage-cdw-page-plan",
		"publication":        "single",
		"descriptor_version": 2,
		"producer_version":   2,
		"entries": []map[string]any{{
			"path":   "plan.json",
			"role":   "primary",
			"size":   len(plan),
			"sha256": "",
		}},
	}
	result := makeZip(t, map[string][]byte{
		"plan.json":        plan,
		"_tmm-result.json": mustJSON(t, manifest),
	})
	if _, err := ReadPlan(result, "linkage-cdw-page-plan", runID, challenge); err == nil {
		t.Fatal("ReadPlan accepted a plan without a checksum")
	}
}

func TestReadMarkdownPreviewValidatesPairs(t *testing.T) {
	svg := []byte(`<svg xmlns="http://www.w3.org/2000/svg"></svg>`)
	scene := []byte(`{"format":"tmm-scene","version":2,"units":"mm"}`)
	svgSum := sha256.Sum256(svg)
	sceneSum := sha256.Sum256(scene)
	manifest := map[string]any{
		"version": 2,
		"format":  "A1",
		"documents": []map[string]any{{
			"source_path": "workspace/document.md",
			"title":       "Document",
			"status":      "ready",
			"pages": []map[string]any{{
				"index": 0, "status": "ready", "preview_path": "page-0.svg", "scene_path": "page-0.scene.json",
			}},
		}},
		"entries": []map[string]any{{
			"path": "page-0.svg", "role": "preview", "size": len(svg), "sha256": hex.EncodeToString(svgSum[:]),
		}, {
			"path": "page-0.scene.json", "role": "scene", "size": len(scene), "sha256": hex.EncodeToString(sceneSum[:]),
		}},
	}
	result := makeZip(t, map[string][]byte{
		"_tmm-md-preview.json": mustJSON(t, manifest),
		"page-0.svg":           svg,
		"page-0.scene.json":    scene,
	})
	if err := ReadMarkdownPreview(result, "A1"); err != nil {
		t.Fatal(err)
	}
}

func TestPublishTreePreservesDeclaredXMCD(t *testing.T) {
	xmcd := []byte(`<worksheet><region><math>q:=42</math></region></worksheet>`)
	sum := sha256.Sum256(xmcd)
	result := makeZip(t, map[string][]byte{
		"_tmm-result.json": mustJSON(t, map[string]any{
			"version":            1,
			"operation":          "linkage",
			"publication":        "tree",
			"descriptor_version": 2,
			"producer_version":   2,
			"entries": []map[string]any{{
				"path":   "mathcad/worksheet.xmcd",
				"role":   "artifact",
				"size":   len(xmcd),
				"sha256": hex.EncodeToString(sum[:]),
			}},
		}),
		"mathcad/worksheet.xmcd": xmcd,
	})
	manifest, err := ReadManifest(result)
	if err != nil {
		t.Fatal(err)
	}
	outputDir := t.TempDir()
	if err := (Publisher{}).PublishTree(result, manifest, outputDir); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(outputDir, "mathcad", "worksheet.xmcd"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, xmcd) {
		t.Fatalf("published XMCD differs from declared member: got %q, want %q", got, xmcd)
	}
}

func TestReadManifestKeepsLegacyCompletedArtifact(t *testing.T) {
	data := []byte("legacy-result")
	sum := sha256.Sum256(data)
	result := makeZip(t, map[string][]byte{
		"_tmm-result.json": mustJSON(t, map[string]any{
			"version":     1,
			"operation":   "linkage",
			"publication": "tree",
			"entries": []map[string]any{{
				"path": "artifact.bin", "role": "artifact", "size": len(data),
				"sha256": hex.EncodeToString(sum[:]),
			}},
		}),
		"artifact.bin": data,
	})
	manifest, err := ReadManifest(result)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.DescriptorVersion != 0 || manifest.ProducerVersion != 0 {
		t.Fatalf("legacy manifest unexpectedly has producer metadata: %#v", manifest)
	}
}

func TestModelFileUsesCanonicalEntrypoint(t *testing.T) {
	input := filepath.Join(t.TempDir(), "appendix.yaml")
	if err := os.WriteFile(input, []byte("bodies: {}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	bundle, err := ModelFile(input)
	if err != nil {
		t.Fatal(err)
	}
	if bundle.Entrypoint != "workspace/model.yaml" {
		t.Fatalf("entrypoint = %q", bundle.Entrypoint)
	}
	archive, err := zip.NewReader(bytes.NewReader(bundle.Data), int64(len(bundle.Data)))
	if err != nil {
		t.Fatal(err)
	}
	if len(archive.File) != 1 || archive.File[0].Name != "workspace/model.yaml" {
		t.Fatalf("archive members = %#v", archive.File)
	}
}
