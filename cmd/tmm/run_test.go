package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"math"
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

func TestTerminalDiagnosticUsesServerExitForWorkerFailure(t *testing.T) {
	serverFailure := &client.Diagnostic{Code: "worker_failure"}
	if got := serverFailure.Class(); got != client.ExitServer {
		t.Fatalf("worker failure exit code = %d, want %d", got, client.ExitServer)
	}

	domainFailure := &client.Diagnostic{Code: "pipeline_failure"}
	if got := domainFailure.Class(); got != client.ExitDomain {
		t.Fatalf("pipeline failure exit code = %d, want %d", got, client.ExitDomain)
	}
}
func TestPositiveFiniteRejectsNonPositiveAndNonFiniteScales(t *testing.T) {
	for _, value := range []float64{0, -1, math.NaN(), math.Inf(1), math.Inf(-1)} {
		if positiveFinite(value) {
			t.Fatalf("positiveFinite(%v) = true", value)
		}
	}
	for _, value := range []float64{0.000001, 1, 1000} {
		if !positiveFinite(value) {
			t.Fatalf("positiveFinite(%v) = false", value)
		}
	}
}

func TestRunKompasSceneGetsChallengeBeforeQuoteAndPublishesDrawing(t *testing.T) {
	challenge := base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{'c'}, 32))
	model := []byte("version: 1\nmechanism: fixture\n")
	planPayload := func(runID string) map[string]any {
		return map[string]any{
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
				"scene_sha256":    strings.Repeat("0", 64),
				"document":        map[string]any{"kind": "part"},
				"operations":      []any{},
			},
			"signature": base64.RawURLEncoding.EncodeToString(bytes.Repeat([]byte{'s'}, 64)),
		}
	}
	makeResult := func(runID string) []byte {
		plan, err := json.Marshal(planPayload(runID))
		if err != nil {
			t.Fatal(err)
		}
		sum := sha256.Sum256(plan)
		manifest, err := json.Marshal(map[string]any{
			"version":     1,
			"operation":   "linkage-cdw-scene-plan",
			"publication": "single",
			"entries": []map[string]any{{
				"path": "plan.json", "role": "primary", "page": nil,
				"size": len(plan), "sha256": hex.EncodeToString(sum[:]),
			}},
		})
		if err != nil {
			t.Fatal(err)
		}
		var result bytes.Buffer
		archive := zip.NewWriter(&result)
		planWriter, err := archive.Create("plan.json")
		if err != nil {
			t.Fatal(err)
		}
		if _, err := planWriter.Write(plan); err != nil {
			t.Fatal(err)
		}
		manifestWriter, err := archive.Create("_tmm-result.json")
		if err != nil {
			t.Fatal(err)
		}
		if _, err := manifestWriter.Write(manifest); err != nil {
			t.Fatal(err)
		}
		if err := archive.Close(); err != nil {
			t.Fatal(err)
		}
		return result.Bytes()
	}

	var submittedRunID string
	var result []byte
	events := make([]string, 0, 6)
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/v1/mechanisms/quote":
			events = append(events, "quote")
			if got := r.Header.Get("Authorization"); got != "Bearer super-secret" {
				t.Errorf("quote authorization = %q", got)
			}
			if got := r.Header.Get("Content-Type"); got != "application/yaml" {
				t.Errorf("quote content type = %q", got)
			}
			body, err := io.ReadAll(r.Body)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(body, model) {
				t.Errorf("quoted model = %q, want %q", body, model)
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"version": 1, "descriptor_version": 2, "source_sha256": strings.Repeat("0", 64), "descriptor_hash": strings.Repeat("1", 64),
				"classification": "known", "matched_mechanism": map[string]any{"id": "fixture"},
				"similarity":      map[string]any{"score": 1, "threshold": 0.9, "structure": 1, "length": 1, "mass": 1, "policy_digest": "p"},
				"requires_credit": false, "can_export": true,
				"balance": map[string]any{"mechanisms_remaining": 2, "mechanisms_reserved": 0},
			})
		case r.Method == http.MethodGet && r.URL.Path == "/v1/capabilities":
			events = append(events, "capabilities")
			if r.Header.Get("Authorization") != "" {
				t.Error("capabilities request leaked API authorization")
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"version": 2, "agent_id": "11111111-1111-4111-8111-111111111111",
				"agent_version": "0.2.0", "challenge": challenge,
				"capabilities": []string{"scene-v2", "api7", "api5-text", "visible-document", "cdw-return"},
			})
		case r.Method == http.MethodPut && strings.HasPrefix(r.URL.Path, "/v1/linkage/cdw/scenes/"):
			events = append(events, "submit")
			submittedRunID = strings.TrimPrefix(r.URL.Path, "/v1/linkage/cdw/scenes/")
			if got := r.Header.Get("Authorization"); got != "Bearer super-secret" {
				t.Errorf("submit authorization = %q", got)
			}
			if err := r.ParseMultipartForm(1 << 20); err != nil {
				t.Fatal(err)
			}
			if len(r.MultipartForm.File) != 2 || r.MultipartForm.File["mechanism"] == nil || r.MultipartForm.File["options"] == nil {
				t.Fatalf("multipart fields = %#v", r.MultipartForm.File)
			}
			mechanism, err := readMultipartField(r.MultipartForm.File["mechanism"][0])
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(mechanism, model) {
				t.Errorf("submitted model = %q, want %q", mechanism, model)
			}
			options, err := readMultipartField(r.MultipartForm.File["options"][0])
			if err != nil {
				t.Fatal(err)
			}
			var parsed map[string]any
			if err := json.Unmarshal(options, &parsed); err != nil {
				t.Fatal(err)
			}
			if parsed["version"] != float64(1) || parsed["agent_challenge"] != challenge || parsed["allow_new_mechanism"] != false || parsed["scene_name"] != "kinematics/a.scene.json" {
				t.Fatalf("paid options = %#v", parsed)
			}
			result = makeResult(submittedRunID)
			w.WriteHeader(http.StatusAccepted)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"version": 1, "run_id": submittedRunID, "operation": "linkage-cdw-scene-plan",
				"state": "queued", "created_at": "2025-01-01T00:00:00Z",
			})
		case r.Method == http.MethodGet && submittedRunID != "" && r.URL.Path == "/v1/runs/"+submittedRunID+"/result":
			w.Header().Set("Content-Type", "application/zip")
			_, _ = w.Write(result)
		case r.Method == http.MethodGet && submittedRunID != "" && r.URL.Path == "/v1/runs/"+submittedRunID:
			sum := sha256.Sum256(result)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"version": 1, "run_id": submittedRunID, "operation": "linkage-cdw-scene-plan",
				"state": "succeeded", "created_at": "2025-01-01T00:00:00Z",
				"result": map[string]any{"sha256": hex.EncodeToString(sum[:]), "size": len(result), "entry_count": 1},
			})
		case r.Method == http.MethodPost && r.URL.Path == "/v1/render":
			events = append(events, "render")
			if r.Header.Get("Authorization") != "" {
				t.Error("render request leaked API authorization")
			}
			if r.Header.Get("X-TMM-Agent-Request") != "1" {
				t.Error("render request omitted renderer marker")
			}
			if _, err := io.ReadAll(r.Body); err != nil {
				t.Error(err)
			}
			drawing := []byte("fake-cdw")
			drawingSum := sha256.Sum256(drawing)
			w.Header().Set("Content-Type", "application/octet-stream")
			w.Header().Set("Content-Disposition", `attachment; filename="result.cdw"`)
			w.Header().Set("X-TMM-Result-Sha256", hex.EncodeToString(drawingSum[:]))
			_, _ = w.Write(drawing)
		default:
			http.NotFound(w, r)
		}
	})
	server := httptest.NewServer(mux)
	defer server.Close()
	t.Setenv("TMM_API_URL", server.URL)
	t.Setenv("TMM_API_TOKEN", "super-secret")
	t.Setenv("TMM_KOMPAS_RENDERER_URL", server.URL)
	modelPath := filepath.Join(t.TempDir(), "model.yaml")
	if err := os.WriteFile(modelPath, model, 0o600); err != nil {
		t.Fatal(err)
	}
	outputPath := filepath.Join(t.TempDir(), "drawing.cdw")
	if got := runKompasScene(modelPath, "kinematics/a.scene.json", 0, false, outputPath); got != client.ExitOK {
		t.Fatalf("runKompasScene exit code = %d", got)
	}
	data, err := os.ReadFile(outputPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "fake-cdw" {
		t.Fatalf("published drawing = %q", data)
	}
	if got := strings.Join(events, ","); got != "capabilities,quote,submit,render" {
		t.Fatalf("request sequence = %q", got)
	}
}

func readMultipartField(header *multipart.FileHeader) ([]byte, error) {
	file, err := header.Open()
	if err != nil {
		return nil, err
	}
	defer file.Close()
	return io.ReadAll(file)
}

func TestResumeRejectsPaidKompasPlans(t *testing.T) {
	for _, operation := range []string{"linkage-cdw-scene-plan", "linkage-cdw-page-plan"} {
		if err := resumableOperationError(operation); err == nil || !strings.Contains(err.Error(), "cannot be resumed") {
			t.Fatalf("resume %s error = %v", operation, err)
		}
	}
	if err := resumableOperationError("render"); err != nil {
		t.Fatalf("resume render error = %v", err)
	}
}

func TestQuoteMechanismRequiresAcceptanceForNewModel(t *testing.T) {
	server := quoteFixtureServer(`{"version":1,"descriptor_version":2,"source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","descriptor_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","classification":"new","matched_mechanism":null,"similarity":{"score":0.1,"threshold":0.9,"structure":0.1,"length":0.1,"mass":0.1,"policy_digest":"p"},"requires_credit":true,"can_export":true,"balance":{"mechanisms_remaining":1,"mechanisms_reserved":0}}`)
	defer server.Close()
	c := &client.Client{BaseURL: server.URL, Token: "test-token", HTTP: server.Client()}
	if accepted, code := quoteMechanism(c, []byte("model"), false); accepted || code != client.ExitUsage {
		t.Fatalf("quote result = (%t, %d), want (false, %d)", accepted, code, client.ExitUsage)
	}
}

func TestQuoteMechanismAllowsStockWithoutAcceptance(t *testing.T) {
	server := quoteFixtureServer(`{"version":1,"descriptor_version":2,"source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","descriptor_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","classification":"stock","matched_mechanism":null,"similarity":{"score":0,"threshold":0.9,"structure":0,"length":0,"mass":0,"policy_digest":"p"},"requires_credit":false,"can_export":true,"balance":{"mechanisms_remaining":0,"mechanisms_reserved":0}}`)
	defer server.Close()
	c := &client.Client{BaseURL: server.URL, Token: "test-token", HTTP: server.Client()}
	if requiresNew, code := quoteMechanism(c, []byte("model"), false); requiresNew || code != client.ExitOK {
		t.Fatalf("quote result = (%t, %d), want (false, %d)", requiresNew, code, client.ExitOK)
	}
}

func TestQuoteMechanismStopsInsufficientBalance(t *testing.T) {
	server := quoteFixtureServer(`{"version":1,"descriptor_version":2,"source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","descriptor_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","classification":"new","matched_mechanism":null,"similarity":{"score":0.1,"threshold":0.9,"structure":0.1,"length":0.1,"mass":0.1,"policy_digest":"p"},"requires_credit":true,"can_export":false,"balance":{"mechanisms_remaining":0,"mechanisms_reserved":1}}`)
	defer server.Close()
	c := &client.Client{BaseURL: server.URL, Token: "test-token", HTTP: server.Client()}
	if accepted, code := quoteMechanism(c, []byte("model"), true); accepted || code != client.ExitAuth {
		t.Fatalf("quote result = (%t, %d), want (false, %d)", accepted, code, client.ExitAuth)
	}
}

func quoteFixtureServer(body string) *httptest.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/mechanisms/quote", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(body))
	})
	return httptest.NewServer(mux)
}

func TestRunMarkdownSendsRawInputsAndPublishesPreview(t *testing.T) {
	model := []byte("bodies: []\n")
	document := []byte("# Document\n")
	preview := markdownPreviewFixture(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/linkage/markdown/render" {
			http.NotFound(w, r)
			return
		}
		if err := r.ParseMultipartForm(1 << 20); err != nil {
			t.Fatal(err)
		}
		if len(r.MultipartForm.File) != 3 {
			t.Fatalf("multipart fields = %#v", r.MultipartForm.File)
		}
		for name, want := range map[string][]byte{
			"mechanism": model,
			"document":  document,
			"options":   []byte(`{"format":"A2"}`),
		} {
			got, err := readMultipartField(r.MultipartForm.File[name][0])
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(got, want) {
				t.Errorf("%s = %q, want %q", name, got, want)
			}
		}
		w.Header().Set("Content-Type", "application/zip")
		_, _ = w.Write(preview)
	}))
	defer server.Close()
	t.Setenv("TMM_API_URL", server.URL)
	t.Setenv("TMM_API_TOKEN", "super-secret")
	modelPath := filepath.Join(t.TempDir(), "model.yaml")
	documentPath := filepath.Join(t.TempDir(), "document.md")
	if err := os.WriteFile(modelPath, model, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(documentPath, document, 0o600); err != nil {
		t.Fatal(err)
	}
	outputPath := filepath.Join(t.TempDir(), "preview.zip")
	if got := runMarkdown(modelPath, documentPath, "A2", outputPath); got != client.ExitOK {
		t.Fatalf("runMarkdown exit code = %d", got)
	}
	got, err := os.ReadFile(outputPath)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, preview) {
		t.Fatal("published preview differs from server response")
	}
}

func TestRunXMCDSendsYAMLAndPublishesOnlyXMCD(t *testing.T) {
	model := []byte("bodies: []\n")
	xmcd := []byte(`<worksheet xmlns="http://schemas.mathsoft.com/worksheet30" version="3.0.3"><regions><region region-id="r1" left="0" top="0" width="100" height="100" align-x="left" align-y="top"/></regions></worksheet>`)
	var submitted bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/v1/linkage/xmcd":
			if got := r.Header.Get("Content-Type"); got != "application/yaml" {
				t.Errorf("Content-Type = %q, want application/yaml", got)
			}
			body, err := io.ReadAll(r.Body)
			if err != nil {
				t.Errorf("read request body: %v", err)
			} else if !bytes.Equal(body, model) {
				t.Errorf("request body = %q, want %q", body, model)
			}
			submitted = true
			w.Header().Set("Content-Type", "application/x-mathcad+xml")
			_, _ = w.Write(xmcd)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	t.Setenv("TMM_API_URL", server.URL)
	t.Setenv("TMM_API_TOKEN", "test-token")
	modelPath := filepath.Join(t.TempDir(), "model.yaml")
	if err := os.WriteFile(modelPath, model, 0o600); err != nil {
		t.Fatal(err)
	}
	outputPath := filepath.Join(t.TempDir(), "worksheet.xmcd")
	if got := runXMCD(modelPath, outputPath); got != client.ExitOK {
		t.Fatalf("runXMCD exit code = %d", got)
	}
	if !submitted {
		t.Fatal("XMCD submission was not received")
	}
	got, err := os.ReadFile(outputPath)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, xmcd) {
		t.Fatalf("published XMCD = %q, want %q", got, xmcd)
	}
}

func markdownPreviewFixture(t *testing.T) []byte {
	t.Helper()
	svg := []byte(`<svg xmlns="http://www.w3.org/2000/svg"></svg>`)
	scene := []byte(`{"format":"tmm-scene","version":2,"units":"mm"}`)
	svgSum := sha256.Sum256(svg)
	sceneSum := sha256.Sum256(scene)
	manifest := map[string]any{
		"version": 2,
		"format":  "A2",
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
	manifestJSON, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	var result bytes.Buffer
	archive := zip.NewWriter(&result)
	for name, data := range map[string][]byte{
		"_tmm-md-preview.json": manifestJSON,
		"page-0.svg":           svg,
		"page-0.scene.json":    scene,
	} {
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
