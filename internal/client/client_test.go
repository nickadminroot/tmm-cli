package client

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestNewDoesNotRequireOrSendToken(t *testing.T) {
	t.Setenv("TMM_API_TOKEN", "must-not-be-used")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "" {
			t.Fatalf("tokenless request sent Authorization %q", got)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte("{\"format\":\"tmm-scene\",\"version\":2,\"units\":\"mm\",\"entities\":[]}"))
	}))
	defer server.Close()
	t.Setenv("TMM_API_URL", server.URL)
	c, err := New()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.ResolveScene([]byte("{\"kind\":\"part\"}")); err != nil {
		t.Fatal(err)
	}
}

func TestComputeMultipartAndChecksum(t *testing.T) {
	bundle := []byte("bundle-zip")
	result := []byte("result-zip")
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
		assertMultipartParts(t, r, map[string][]byte{
			"request": []byte("{\"version\":1,\"operation\":\"linkage\",\"entrypoint\":\"workspace/model.yaml\",\"options\":{}}"),
			"bundle":  bundle,
		})
		w.Header().Set("Content-Type", "application/zip")
		w.Header().Set("X-Result-Sha256", hex.EncodeToString(sum[:]))
		_, _ = w.Write(result)
	}))
	defer server.Close()
	c := &Client{BaseURL: server.URL, UserAgent: "test", HTTP: server.Client()}
	got, err := c.Compute(Envelope{Version: 1, Operation: "linkage", Entrypoint: "workspace/model.yaml", Options: map[string]any{}}, bundle)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, result) {
		t.Fatalf("result = %q, want %q", got, result)
	}
}

func TestComputeRejectsInvalidChecksum(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/zip")
		w.Header().Set("X-Result-Sha256", strings.Repeat("a", 64))
		_, _ = w.Write([]byte("result"))
	}))
	defer server.Close()
	c := &Client{BaseURL: server.URL, HTTP: server.Client()}
	if _, err := c.Compute(Envelope{Version: 1, Operation: "render", Entrypoint: "workspace/input.scene.json"}, []byte("bundle")); err == nil || !strings.Contains(err.Error(), "checksum mismatch") {
		t.Fatalf("Compute error = %v, want checksum mismatch", err)
	}
}

func TestPublicJSONSceneAndCDWContracts(t *testing.T) {
	scene := []byte("{\"kind\":\"part\",\"entities\":[]}")
	render := []byte("{\"format\":\"tmm-scene\",\"version\":2,\"units\":\"mm\",\"entities\":[]}")
	challenge := "renderer-challenge"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "" {
			t.Fatalf("public request sent Authorization %q", got)
		}
		if r.Method != http.MethodPost || r.Header.Get("Content-Type") != "application/json" {
			t.Fatalf("request = %s %s %q", r.Method, r.URL.Path, r.Header.Get("Content-Type"))
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}
		var envelope map[string]any
		if err := json.Unmarshal(body, &envelope); err != nil {
			t.Fatal(err)
		}
		switch r.URL.Path {
		case "/v1/scenes/resolve":
			if !bytes.Equal(body, scene) {
				t.Fatalf("resolve body = %s, want %s", body, scene)
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(render)
		case "/v1/cdw/scene":
			if _, ok := envelope["scene"]; !ok {
				t.Fatal("scene envelope omitted scene")
			}
			assertPublicPlanOptions(t, envelope, challenge)
			w.Header().Set("Content-Type", "application/zip")
			_, _ = w.Write([]byte("scene-plan-zip"))
		case "/v1/cdw/render":
			if _, ok := envelope["render"]; !ok {
				t.Fatal("render envelope omitted render")
			}
			assertPublicPlanOptions(t, envelope, challenge)
			w.Header().Set("Content-Type", "application/zip")
			_, _ = w.Write([]byte("render-plan-zip"))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	c := &Client{BaseURL: server.URL, HTTP: server.Client()}
	if got, err := c.ResolveScene(scene); err != nil || !bytes.Equal(got, render) {
		t.Fatalf("ResolveScene = %q, %v", got, err)
	}
	if got, err := c.RenderCDWSceneContext(context.Background(), scene, challenge, map[string]any{"scale": 2.5}); err != nil || string(got) != "scene-plan-zip" {
		t.Fatalf("RenderCDWSceneContext = %q, %v", got, err)
	}
	if got, err := c.RenderCDWRenderContext(context.Background(), render, challenge); err != nil || string(got) != "render-plan-zip" {
		t.Fatalf("RenderCDWRenderContext = %q, %v", got, err)
	}
}

func assertPublicPlanOptions(t *testing.T, envelope map[string]any, challenge string) {
	t.Helper()
	options, ok := envelope["options"].(map[string]any)
	if !ok || options["version"] != float64(1) || options["agent_challenge"] != challenge {
		t.Fatalf("public options = %#v", envelope["options"])
	}
}

func TestDecodeErrorKeepsTypedDiagnostics(t *testing.T) {
	response := &http.Response{
		StatusCode: 422,
		Body:       io.NopCloser(strings.NewReader("{\"detail\":{\"code\":\"pipeline_failure\",\"message\":\"singular matrix\",\"field\":\"\",\"line\":7,\"column\":3,\"stage\":\"forces\",\"pipeline\":[{\"id\":\"model\",\"label\":\"Проверка модели\",\"state\":\"passed\",\"message\":null},{\"id\":\"forces\",\"label\":\"Силовой расчёт\",\"state\":\"failed\",\"message\":\"singular matrix\"},{\"id\":\"artifacts\",\"label\":\"Формирование результатов\",\"state\":\"skipped\",\"message\":null}]}}")),
	}
	err := decodeError(response)
	if err.Code != "pipeline_failure" || err.Message != "singular matrix" || err.Stage != "forces" || err.Line != 7 || err.Column != 3 || len(err.Pipeline) != 3 {
		t.Fatalf("diagnostic = %#v", err)
	}
}

func TestGetXMCDUsesTokenlessDirectEndpoint(t *testing.T) {
	mechanism := []byte("bodies: []\n")
	xmcd := []byte("<worksheet xmlns=\"http://schemas.mathsoft.com/worksheet30\" version=\"3.0.3\"><regions/></worksheet>")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/linkage/xmcd" || r.Header.Get("Authorization") != "" {
			t.Fatalf("request = %s %s auth=%q", r.Method, r.URL.Path, r.Header.Get("Authorization"))
		}
		if got := r.Header.Get("Content-Type"); got != "application/yaml" {
			t.Fatalf("Content-Type = %q", got)
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(body, mechanism) {
			t.Fatalf("body = %q", body)
		}
		w.Header().Set("Content-Type", "application/x-mathcad+xml; charset=utf-8")
		_, _ = w.Write(xmcd)
	}))
	defer server.Close()
	c := &Client{BaseURL: server.URL, HTTP: server.Client()}
	got, err := c.GetXMCD(mechanism)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, xmcd) {
		t.Fatalf("XMCD = %q", got)
	}
}

func TestRenderMarkdownAndYAMLCDWAreTokenless(t *testing.T) {
	mechanism := []byte("bodies: []\n")
	document := []byte("# Sheet\n")
	scenes := []byte("{\"velocity-plan.scene.json\":{\"kind\":\"velocity-plan\"}}")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "" {
			t.Fatal("request leaked Authorization")
		}
		switch r.URL.Path {
		case "/v1/linkage/markdown/render":
			assertMultipartParts(t, r, map[string][]byte{
				"mechanism": mechanism,
				"document":  document,
				"scenes":    scenes,
				"options":   []byte("{\"format\":\"A2\",\"source_path\":\"kinematics/page.md\"}"),
			})
			w.Header().Set("Content-Type", "application/zip")
			_, _ = w.Write([]byte("markdown-zip"))
		case "/v1/linkage/cdw/scene":
			assertMultipartParts(t, r, map[string][]byte{
				"mechanism": mechanism,
				"options":   []byte("{\"agent_challenge\":\"challenge\",\"scene_name\":\"kinematics/a.scene.json\",\"version\":1}"),
			})
			w.Header().Set("Content-Type", "application/zip")
			_, _ = w.Write([]byte("scene-plan-zip"))
		case "/v1/linkage/cdw/page":
			assertMultipartParts(t, r, map[string][]byte{
				"mechanism": mechanism,
				"document":  document,
				"scenes":    scenes,
				"options":   []byte("{\"agent_challenge\":\"challenge\",\"format\":\"A2\",\"page\":1,\"source_path\":\"kinematics/page.md\",\"version\":1}"),
			})
			w.Header().Set("Content-Type", "application/zip")
			_, _ = w.Write([]byte("page-plan-zip"))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	c := &Client{BaseURL: server.URL, HTTP: server.Client()}
	if got, err := c.RenderMarkdownContext(context.Background(), mechanism, document, "A2", scenes, "kinematics/page.md"); err != nil || string(got) != "markdown-zip" {
		t.Fatalf("RenderMarkdownContext = %q, %v", got, err)
	}
	if got, err := c.RenderLinkageCDWSceneContext(context.Background(), mechanism, "kinematics/a.scene.json", "challenge", nil); err != nil || string(got) != "scene-plan-zip" {
		t.Fatalf("RenderLinkageCDWSceneContext = %q, %v", got, err)
	}
	if got, err := c.RenderLinkageCDWPageContext(context.Background(), mechanism, document, "A2", "challenge", 1, "kinematics/page.md", scenes); err != nil || string(got) != "page-plan-zip" {
		t.Fatalf("RenderLinkageCDWPageContext = %q, %v", got, err)
	}
}

func TestScenePayloadValidationRejectsNonObjects(t *testing.T) {
	c := &Client{BaseURL: "http://127.0.0.1:1", HTTP: http.DefaultClient}
	for _, payload := range []string{"[]", "null", "{\"scene.json\":null}", "{\"scene.json\":[]}"} {
		if _, err := c.RenderMarkdownContext(context.Background(), []byte("model"), []byte("doc"), "A1", []byte(payload)); err == nil {
			t.Fatalf("payload %s accepted", payload)
		}
	}
}

func assertMultipartParts(t *testing.T, r *http.Request, want map[string][]byte) {
	t.Helper()
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		t.Fatal(err)
	}
	if len(r.MultipartForm.File) != len(want) {
		t.Fatalf("multipart fields = %#v, want %v", r.MultipartForm.File, want)
	}
	for name, expected := range want {
		file, _, err := r.FormFile(name)
		if err != nil {
			t.Fatalf("multipart %s: %v", name, err)
		}
		body, readErr := io.ReadAll(file)
		file.Close()
		if readErr != nil {
			t.Fatal(readErr)
		}
		if !bytes.Equal(body, expected) {
			t.Errorf("multipart %s = %q, want %q", name, body, expected)
		}
	}
}
