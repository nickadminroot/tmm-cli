package client

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestNewRequiresTokenForEveryAPIURL(t *testing.T) {
	t.Setenv("TMM_API_TOKEN", "")

	for _, base := range []string{
		"http://localhost:8000",
		"http://127.0.0.1:8000",
		"https://api.example.test",
		"https://example.test",
	} {
		t.Run(base, func(t *testing.T) {
			t.Setenv("TMM_API_URL", base)
			_, err := New()
			if err == nil {
				t.Fatal("New() error = nil, want missing-token error")
			}
			if !strings.Contains(err.Error(), "TMM_API_TOKEN is required") {
				t.Fatalf("New() error = %v, want missing-token diagnostic", err)
			}
		})
	}
}

func TestNewAnonymousDoesNotRequireOrSendToken(t *testing.T) {
	t.Setenv("TMM_API_TOKEN", "secret-that-must-not-be-forwarded")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "" {
			t.Fatalf("anonymous request sent Authorization %q", got)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"format":"tmm-scene","version":2,"units":"mm","entities":[]}`))
	}))
	defer server.Close()
	t.Setenv("TMM_API_URL", server.URL)
	c, err := NewAnonymous()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.ResolveScene([]byte(`{"kind":"part"}`)); err != nil {
		t.Fatal(err)
	}
}

func TestPublicJSONSceneAndCDWContracts(t *testing.T) {
	scene := []byte(`{"kind":"part","entities":[]}`)
	render := []byte(`{"format":"tmm-scene","version":2,"units":"mm","entities":[]}`)
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
		Body:       io.NopCloser(strings.NewReader(`{"detail":{"code":"pipeline_failure","message":"singular matrix","field":"","line":7,"column":3,"stage":"forces","pipeline":[{"id":"model","label":"Проверка модели","state":"passed","message":null},{"id":"forces","label":"Силовой расчёт","state":"failed","message":"singular matrix"},{"id":"artifacts","label":"Формирование результатов","state":"skipped","message":null}]}}`)),
	}

	err := decodeError(response)
	if err.Code != "pipeline_failure" || err.Message != "singular matrix" {
		t.Fatalf("diagnostic = %#v", err)
	}
	if err.Stage != "forces" || err.Line != 7 || err.Column != 3 {
		t.Fatalf("location = %#v", err)
	}
	if len(err.Pipeline) != 3 || err.Pipeline[1].State != "failed" {
		t.Fatalf("pipeline = %#v", err.Pipeline)
	}
}

func TestMechanismAndPaidRequestsUseExactContracts(t *testing.T) {
	mechanism := []byte("bodies: []\n")
	document := []byte("# Sheet\n")
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/mechanisms/quote":
			if r.Method != http.MethodPost || r.Header.Get("Content-Type") != "application/yaml" {
				t.Fatalf("quote request = %s %s %q", r.Method, r.URL.Path, r.Header.Get("Content-Type"))
			}
			body, err := io.ReadAll(r.Body)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(body, mechanism) {
				t.Fatalf("quote body = %q, want %q", body, mechanism)
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"version":1,"descriptor_version":2,"source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","descriptor_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","classification":"known","matched_mechanism":{"id":"m-1"},"similarity":{"score":1,"threshold":0.9,"structure":1,"length":1,"mass":1,"policy_digest":"p"},"requires_credit":false,"can_export":true,"balance":{"mechanisms_remaining":2,"mechanisms_reserved":0}}`))
		case "/v1/linkage/markdown/render":
			assertMultipartParts(t, r, map[string][]byte{
				"mechanism": mechanism,
				"document":  document,
				"options":   []byte(`{"format":"A2"}`),
			})
			_, _ = w.Write([]byte("markdown-zip"))
		case "/v1/linkage/cdw/scenes/run-scene":
			assertMultipartParts(t, r, map[string][]byte{
				"mechanism": mechanism,
				"options":   []byte(`{"agent_challenge":"challenge","allow_new_mechanism":false,"scene_name":"scene.json","version":1}`),
			})
			w.WriteHeader(http.StatusAccepted)
			_, _ = w.Write([]byte(`{"version":1,"run_id":"run-scene","operation":"linkage-cdw-scene-plan","state":"queued"}`))
		case "/v1/linkage/xmcd/run-xmcd":
			assertMultipartParts(t, r, map[string][]byte{
				"mechanism": mechanism,
				"options":   []byte(`{"version":1,"allow_new_mechanism":true}`),
			})
			w.WriteHeader(http.StatusAccepted)
			_, _ = w.Write([]byte(`{"version":1,"run_id":"run-xmcd","operation":"linkage-xmcd","state":"queued"}`))
		case "/v1/linkage/cdw/pages/run-page":
			assertMultipartParts(t, r, map[string][]byte{
				"mechanism": mechanism,
				"document":  document,
				"options":   []byte(`{"agent_challenge":"challenge","allow_new_mechanism":true,"format":"A3","page":2,"version":1}`),
			})
			w.WriteHeader(http.StatusAccepted)
			_, _ = w.Write([]byte(`{"version":1,"run_id":"run-page","operation":"linkage-cdw-page-plan","state":"queued"}`))
		default:
			http.NotFound(w, r)
		}
	})
	server := httptest.NewServer(mux)
	defer server.Close()
	c := &Client{BaseURL: server.URL, Token: "test-token", HTTP: server.Client(), RetryMax: time.Second}

	quote, err := c.Quote(mechanism)
	if err != nil {
		t.Fatal(err)
	}
	if quote.Classification != "known" || quote.MatchedMechanism["id"] != "m-1" {
		t.Fatalf("quote = %#v", quote)
	}
	if got, err := c.RenderMarkdown(mechanism, document, "A2"); err != nil || string(got) != "markdown-zip" {
		t.Fatalf("RenderMarkdown = %q, %v", got, err)
	}
	if _, err := c.SubmitCDWScene("run-scene", mechanism, "scene.json", "challenge", false, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := c.SubmitXMCD("run-xmcd", mechanism, true); err != nil {
		t.Fatal(err)
	}
	if _, err := c.SubmitCDWPage("run-page", mechanism, document, "A3", "challenge", true, 2); err != nil {
		t.Fatal(err)
	}
}

func TestGetXMCDUsesFreeDirectEndpoint(t *testing.T) {
	mechanism := []byte("bodies: []\n")
	xmcd := []byte(`<worksheet xmlns="http://schemas.mathsoft.com/worksheet30" version="3.0.3"><regions/></worksheet>`)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/linkage/xmcd" {
			t.Fatalf("request = %s %s", r.Method, r.URL.Path)
		}
		if got := r.Header.Get("Content-Type"); got != "application/yaml" {
			t.Fatalf("Content-Type = %q, want application/yaml", got)
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(body, mechanism) {
			t.Fatalf("body = %q, want %q", body, mechanism)
		}
		w.Header().Set("Content-Type", "application/x-mathcad+xml; charset=utf-8")
		_, _ = w.Write(xmcd)
	}))
	defer server.Close()

	c := &Client{BaseURL: server.URL, Token: "test-token", HTTP: server.Client(), RetryMax: time.Second}
	got, err := c.GetXMCD(mechanism)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, xmcd) {
		t.Fatalf("XMCD = %q, want %q", got, xmcd)
	}
}

func TestRenderMarkdownContextForwardsSourcePath(t *testing.T) {
	mechanism := []byte("bodies: []\n")
	document := []byte("# Sheet\n")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/linkage/markdown/render" {
			t.Fatalf("request = %s %s", r.Method, r.URL.Path)
		}
		assertMultipartParts(t, r, map[string][]byte{
			"mechanism": mechanism,
			"document":  document,
			"options":   []byte(`{"format":"A1","source_path":"kinematics/velocity-analysis.md"}`),
		})
		_, _ = w.Write([]byte("markdown-zip"))
	}))
	defer server.Close()

	c := &Client{
		BaseURL:  server.URL,
		Token:    "test-token",
		HTTP:     server.Client(),
		RetryMax: time.Second,
	}
	got, err := c.RenderMarkdownContext(
		context.Background(),
		mechanism,
		document,
		"A1",
		"kinematics/velocity-analysis.md",
	)
	if err != nil || string(got) != "markdown-zip" {
		t.Fatalf("RenderMarkdownContext = %q, %v", got, err)
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

func TestMechanismBalanceAndRegistryDecode(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/mechanisms/balance", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"version":1,"mechanisms_granted":10,"mechanisms_used":2,"mechanisms_reserved":1,"mechanisms_remaining":7,"account_status":"active","billing_status":"normal"}`))
	})
	mux.HandleFunc("/v1/mechanisms", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"version":1,"items":[{"id":"m-1","display_number":1,"descriptor_version":1,"descriptor_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","body_count":3,"joint_counts":{"revolute":2},"assur_group_count":1,"policy_digest":"p","activated_at":"2025-01-01T00:00:00Z","last_used_at":null}],"next_cursor":"next"}`))
	})
	server := httptest.NewServer(mux)
	defer server.Close()
	c := &Client{BaseURL: server.URL, Token: "test-token", HTTP: server.Client()}
	balance, err := c.MechanismBalance()
	if err != nil {
		t.Fatal(err)
	}
	if balance.MechanismsRemaining != 7 || balance.AccountStatus != "active" {
		t.Fatalf("balance = %#v", balance)
	}
	registry, err := c.MechanismRegistry()
	if err != nil {
		t.Fatal(err)
	}
	if registry.Version != 1 || len(registry.Items) != 1 || registry.Items[0].JointCounts["revolute"] != 2 || registry.NextCursor == nil || *registry.NextCursor != "next" {
		t.Fatalf("registry = %#v", registry)
	}
}
func TestQuoteRejectsVersionOneDescriptor(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"version":1,"descriptor_version":1,"source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","descriptor_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","classification":"new","matched_mechanism":null,"similarity":{"score":1,"threshold":0.9,"structure":1,"length":1,"mass":1,"policy_digest":"p"},"requires_credit":true,"can_export":false,"balance":{"mechanisms_remaining":0,"mechanisms_reserved":0}}`))
	}))
	defer server.Close()
	client := &Client{BaseURL: server.URL, Token: "test-token", HTTP: server.Client()}
	if _, err := client.Quote([]byte("schema: linkage/v1\n")); err == nil {
		t.Fatal("Quote accepted a version-one descriptor")
	}
}

func TestResultFailsClosedWithoutStatusIntegrity(t *testing.T) {
	c := &Client{}
	for _, status := range []*Status{
		{RunID: "run"},
		{RunID: "run", Result: &struct {
			SHA256     string `json:"sha256"`
			Size       int64  `json:"size"`
			EntryCount int    `json:"entry_count"`
		}{SHA256: strings.Repeat("a", 64), Size: -1}},
		{RunID: "run", Result: &struct {
			SHA256     string `json:"sha256"`
			Size       int64  `json:"size"`
			EntryCount int    `json:"entry_count"`
		}{SHA256: strings.Repeat("A", 64), Size: 0}},
	} {
		if _, err := c.ResultContext(context.Background(), status); err == nil {
			t.Fatalf("ResultContext accepted invalid status %#v", status)
		}
	}
}
