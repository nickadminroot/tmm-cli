package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/nickadminroot/tmm/apps/tmm-cli/internal/client"
)

func TestWriteDiagnosticIncludesFullPipeline(t *testing.T) {
	detail := &client.Diagnostic{
		Code:    "worker_failure",
		Message: "worker execution failed",
		Stage:   "execution",
		Pipeline: []client.DiagnosticStep{
			{ID: "model", Label: "Проверка модели", State: "passed"},
			{ID: "artifacts", Label: "Формирование результатов", State: "failed", Message: "worker execution failed"},
		},
	}
	var output strings.Builder
	writeDiagnostic(&output, detail)
	for _, want := range []string{
		"worker execution failed (worker_failure)",
		"Этап: execution",
		"[пройден] Проверка модели",
		"[ошибка] Формирование результатов",
	} {
		if !strings.Contains(output.String(), want) {
			t.Fatalf("diagnostic output = %q, missing %q", output.String(), want)
		}
	}
}

func TestPositiveFiniteRejectsNonPositiveAndNonFiniteScales(t *testing.T) {
	for _, value := range []float64{0, -1} {
		if positiveFinite(value) {
			t.Fatalf("positiveFinite(%v) = true", value)
		}
	}
}

func TestRunDomainUsesTokenlessComputeAndPublishesTree(t *testing.T) {
	model := []byte("schema: linkage/v2\nbodies: []\n")
	result := resultZIP(t, "linkage", "tree", map[string][]byte{"workspace/result.txt": []byte("ok")})
	sum := sha256.Sum256(result)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/compute" {
			t.Fatalf("request = %s %s", r.Method, r.URL.Path)
		}
		if r.Header.Get("Authorization") != "" {
			t.Fatal("compute request leaked Authorization")
		}
		if err := r.ParseMultipartForm(1 << 20); err != nil {
			t.Fatal(err)
		}
		if len(r.MultipartForm.File["request"]) != 1 || len(r.MultipartForm.File["bundle"]) != 1 {
			t.Fatalf("multipart fields = %#v", r.MultipartForm.File)
		}
		requestBytes, err := readMultipartField(r.MultipartForm.File["request"][0])
		if err != nil {
			t.Fatal(err)
		}
		var envelope map[string]any
		if err := json.Unmarshal(requestBytes, &envelope); err != nil {
			t.Fatal(err)
		}
		if envelope["operation"] != "linkage" || envelope["entrypoint"] != "workspace/model.yaml" {
			t.Fatalf("request envelope = %#v", envelope)
		}
		w.Header().Set("Content-Type", "application/zip")
		w.Header().Set("X-Result-Sha256", hex.EncodeToString(sum[:]))
		_, _ = w.Write(result)
	}))
	defer server.Close()
	t.Setenv("TMM_API_URL", server.URL)
	t.Setenv("TMM_API_TOKEN", "secret-that-must-not-be-used")
	modelPath := filepath.Join(t.TempDir(), "model.yaml")
	if err := os.WriteFile(modelPath, model, 0o600); err != nil {
		t.Fatal(err)
	}
	outputDir := filepath.Join(t.TempDir(), "out")
	if got := runDomain("linkage", modelPath, outputDir, map[string]any{}); got != client.ExitOK {
		t.Fatalf("runDomain exit code = %d", got)
	}
	got, err := os.ReadFile(filepath.Join(outputDir, "workspace", "result.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "ok" {
		t.Fatalf("published result = %q", got)
	}
}

func TestRunXMCDSendsTokenlessYAMLAndPublishesXMCD(t *testing.T) {
	model := []byte("schema: linkage/v2\nbodies: []\n")
	xmcd := []byte("<worksheet xmlns=\"http://schemas.mathsoft.com/worksheet30\" version=\"3.0.3\"><regions/></worksheet>")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/linkage/xmcd" || r.Header.Get("Authorization") != "" {
			t.Fatalf("request = %s %s auth=%q", r.Method, r.URL.Path, r.Header.Get("Authorization"))
		}
		body, err := io.ReadAll(r.Body)
		if err != nil || !bytes.Equal(body, model) {
			t.Fatalf("request body = %q, err=%v", body, err)
		}
		w.Header().Set("Content-Type", "application/x-mathcad+xml")
		_, _ = w.Write(xmcd)
	}))
	defer server.Close()
	t.Setenv("TMM_API_URL", server.URL)
	t.Setenv("TMM_API_TOKEN", "secret-that-must-not-be-used")
	modelPath := filepath.Join(t.TempDir(), "model.yaml")
	if err := os.WriteFile(modelPath, model, 0o600); err != nil {
		t.Fatal(err)
	}
	outputPath := filepath.Join(t.TempDir(), "worksheet.xmcd")
	if got := runXMCD(modelPath, outputPath); got != client.ExitOK {
		t.Fatalf("runXMCD exit code = %d", got)
	}
	got, err := os.ReadFile(outputPath)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, xmcd) {
		t.Fatalf("published XMCD = %q", got)
	}
}

func TestRunKompasSceneUsesSynchronousTokenlessPlan(t *testing.T) {
	challenge := base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{'c'}, 32))
	model := []byte("schema: linkage/v2\nbodies: []\n")
	planZIP := publicPlanZIP(t, "linkage-cdw-scene-plan", challenge)
	var sawAuthorization bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "" {
			sawAuthorization = true
		}
		switch r.URL.Path {
		case "/v1/capabilities":
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"version": 2, "agent_id": "11111111-1111-4111-8111-111111111111",
				"agent_version": "0.2.0", "challenge": challenge,
				"capabilities": []string{"scene-v2", "api7", "api5-text", "visible-document", "cdw-return"},
			})
		case "/v1/linkage/cdw/scene":
			if r.Method != http.MethodPost {
				t.Fatalf("scene method = %s", r.Method)
			}
			if err := r.ParseMultipartForm(1 << 20); err != nil {
				t.Fatal(err)
			}
			if len(r.MultipartForm.File["mechanism"]) != 1 || len(r.MultipartForm.File["options"]) != 1 {
				t.Fatalf("multipart fields = %#v", r.MultipartForm.File)
			}
			options, err := readMultipartField(r.MultipartForm.File["options"][0])
			if err != nil {
				t.Fatal(err)
			}
			var parsed map[string]any
			if err := json.Unmarshal(options, &parsed); err != nil {
				t.Fatal(err)
			}
			if parsed["version"] != float64(1) || parsed["scene_name"] != "kinematics/a.scene.json" || parsed["agent_challenge"] != challenge {
				t.Fatalf("options = %#v", parsed)
			}
			w.Header().Set("Content-Type", "application/zip")
			_, _ = w.Write(planZIP)
		case "/v1/render":
			drawing := []byte("fake-cdw")
			drawingSum := sha256.Sum256(drawing)
			w.Header().Set("Content-Type", "application/octet-stream")
			w.Header().Set("Content-Disposition", `attachment; filename="result.cdw"`)
			w.Header().Set("X-TMM-Result-Sha256", hex.EncodeToString(drawingSum[:]))
			_, _ = w.Write(drawing)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	t.Setenv("TMM_API_URL", server.URL)
	t.Setenv("TMM_API_TOKEN", "secret-that-must-not-be-used")
	t.Setenv("TMM_KOMPAS_RENDERER_URL", server.URL)
	modelPath := filepath.Join(t.TempDir(), "model.yaml")
	if err := os.WriteFile(modelPath, model, 0o600); err != nil {
		t.Fatal(err)
	}
	outputPath := filepath.Join(t.TempDir(), "drawing.cdw")
	if got := runKompasScene(modelPath, "kinematics/a.scene.json", 0, outputPath); got != client.ExitOK {
		t.Fatalf("runKompasScene exit code = %d", got)
	}
	data, err := os.ReadFile(outputPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "fake-cdw" {
		t.Fatalf("published drawing = %q", data)
	}
	if sawAuthorization {
		t.Fatal("tokenless KOMPAS flow sent Authorization")
	}
}

func resultZIP(t *testing.T, operation, publication string, members map[string][]byte) []byte {
	t.Helper()
	var result bytes.Buffer
	archive := zip.NewWriter(&result)
	entries := make([]map[string]any, 0, len(members))
	for name, data := range members {
		sum := sha256.Sum256(data)
		writer, err := archive.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := writer.Write(data); err != nil {
			t.Fatal(err)
		}
		entries = append(entries, map[string]any{"path": name, "role": "artifact", "size": len(data), "sha256": hex.EncodeToString(sum[:])})
	}
	manifest, err := json.Marshal(map[string]any{"version": 1, "operation": operation, "publication": publication, "entries": entries})
	if err != nil {
		t.Fatal(err)
	}
	writer, err := archive.Create("_tmm-result.json")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Write(manifest); err != nil {
		t.Fatal(err)
	}
	if err := archive.Close(); err != nil {
		t.Fatal(err)
	}
	return result.Bytes()
}

func publicPlanZIP(t *testing.T, operation, challenge string) []byte {
	t.Helper()
	plan := map[string]any{
		"format": "tmm-kompas-plan", "version": 1, "algorithm": "ed25519", "key_id": "default",
		"payload": map[string]any{
			"operation": "kompas-plan", "job_id": "11111111-1111-4111-8111-111111111111",
			"agent_challenge": challenge, "issued_at": "2025-01-01T00:00:00Z", "expires_at": "2025-01-01T00:05:00Z",
			"scene_sha256": strings.Repeat("0", 64), "document": map[string]any{"kind": "part"}, "operations": []any{},
		},
		"signature": base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{'s'}, 64)),
	}
	planBytes, err := json.Marshal(plan)
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(planBytes)
	manifest, err := json.Marshal(map[string]any{
		"version": 1, "operation": operation, "publication": "single",
		"entries": []map[string]any{{"path": "plan.json", "role": "primary", "size": len(planBytes), "sha256": hex.EncodeToString(sum[:])}},
	})
	if err != nil {
		t.Fatal(err)
	}
	var result bytes.Buffer
	archive := zip.NewWriter(&result)
	for name, data := range map[string][]byte{"plan.json": planBytes, "_tmm-result.json": manifest} {
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
	return result.Bytes()
}

func readMultipartField(header *multipart.FileHeader) ([]byte, error) {
	file, err := header.Open()
	if err != nil {
		return nil, err
	}
	defer file.Close()
	return io.ReadAll(file)
}
