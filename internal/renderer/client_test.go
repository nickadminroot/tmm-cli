package renderer

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestClientUsesSeparateLoopbackProtocolV2(t *testing.T) {
	challenge := "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "" {
			t.Error("renderer request leaked an API authorization header")
		}
		if r.Header.Get("X-TMM-Agent-Request") != "1" {
			t.Error("renderer request marker missing")
		}
		w.Header().Set("Content-Type", "application/json")
		if r.Method == http.MethodGet {
			_ = json.NewEncoder(w).Encode(Capabilities{
				Version:         ProtocolVersion,
				RendererID:      "11111111-1111-4111-8111-111111111111",
				RendererVersion: "0.2.0",
				Challenge:       challenge,
				Capabilities:    []string{"scene-v2", "api7", "api5-text", "visible-document", "cdw-return"},
			})
			return
		}
		data := []byte("fake-cdw")
		sum := sha256.Sum256(data)
		w.Header().Set("Content-Type", "application/octet-stream")
		w.Header().Set("Content-Disposition", `attachment; filename="result.cdw"`)
		w.Header().Set("X-TMM-Result-Sha256", hex.EncodeToString(sum[:]))
		_, _ = w.Write(data)
	}))
	defer server.Close()

	t.Setenv("TMM_KOMPAS_RENDERER_URL", server.URL)
	client, err := New()
	if err != nil {
		t.Fatal(err)
	}
	capabilities, err := client.GetCapabilities()
	if err != nil {
		t.Fatal(err)
	}
	if capabilities.Challenge != challenge {
		t.Fatalf("challenge = %q, want %q", capabilities.Challenge, challenge)
	}
	data, err := client.Render([]byte(`{"format":"tmm-kompas-plan"}`))
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "fake-cdw" {
		t.Fatalf("render data = %q", data)
	}
}

func TestGetCapabilitiesRequiresProtocolV2AndFullCapabilities(t *testing.T) {
	challenge := "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M"
	tests := []struct {
		name string
		body Capabilities
	}{
		{
			name: "old protocol",
			body: Capabilities{
				Version:    1,
				RendererID: "11111111-1111-4111-8111-111111111111",
				Challenge:  challenge,
			},
		},
		{
			name: "missing capability",
			body: Capabilities{
				Version:      ProtocolVersion,
				RendererID:   "11111111-1111-4111-8111-111111111111",
				Challenge:    challenge,
				Capabilities: []string{"scene-v2", "api7", "api5-text", "visible-document"},
			},
		},
		{
			name: "invalid renderer id",
			body: Capabilities{
				Version:      ProtocolVersion,
				RendererID:   "renderer-test",
				Challenge:    challenge,
				Capabilities: []string{"scene-v2", "api7", "api5-text", "visible-document", "cdw-return"},
			},
		},
		{
			name: "invalid renderer version",
			body: Capabilities{
				Version:         ProtocolVersion,
				RendererID:      "11111111-1111-4111-8111-111111111111",
				RendererVersion: "\x00",
				Challenge:       challenge,
				Capabilities:    []string{"scene-v2", "api7", "api5-text", "visible-document", "cdw-return"},
			},
		},
		{
			name: "duplicate capability",
			body: Capabilities{
				Version:         ProtocolVersion,
				RendererID:      "11111111-1111-4111-8111-111111111111",
				RendererVersion: "0.2.0",
				Challenge:       challenge,
				Capabilities:    []string{"scene-v2", "scene-v2", "api7", "api5-text", "visible-document", "cdw-return"},
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(test.body)
			}))
			defer server.Close()
			t.Setenv("TMM_KOMPAS_RENDERER_URL", server.URL)
			client, err := New()
			if err != nil {
				t.Fatal(err)
			}
			_, err = client.GetCapabilities()
			rendererErr, ok := err.(*Error)
			if !ok || rendererErr.Code != "agent_incompatible" {
				t.Fatalf("capability error = %#v, want agent_incompatible", err)
			}
		})
	}
}

func TestRenderRequiresValidChecksum(t *testing.T) {
	challenge := "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M"
	tests := []struct {
		name     string
		checksum string
	}{
		{name: "missing"},
		{name: "mismatch", checksum: strings.Repeat("0", sha256.Size*2)},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method == http.MethodGet {
					w.Header().Set("Content-Type", "application/json")
					_ = json.NewEncoder(w).Encode(Capabilities{
						Version:         ProtocolVersion,
						RendererID:      "11111111-1111-4111-8111-111111111111",
						RendererVersion: "0.2.0",
						Challenge:       challenge,
						Capabilities:    []string{"scene-v2", "api7", "api5-text", "visible-document", "cdw-return"},
					})
					return
				}
				data := []byte("fake-cdw")
				w.Header().Set("Content-Type", "application/octet-stream")
				w.Header().Set("Content-Disposition", `attachment; filename="result.cdw"`)
				if test.checksum != "" {
					w.Header().Set("X-TMM-Result-Sha256", test.checksum)
				}
				_, _ = w.Write(data)
			}))
			defer server.Close()
			t.Setenv("TMM_KOMPAS_RENDERER_URL", server.URL)
			client, err := New()
			if err != nil {
				t.Fatal(err)
			}
			if _, err := client.GetCapabilities(); err != nil {
				t.Fatal(err)
			}
			_, err = client.Render([]byte(`{"format":"tmm-kompas-plan"}`))
			rendererErr, ok := err.(*Error)
			if !ok || rendererErr.Code != "agent_protocol" {
				t.Fatalf("checksum error = %#v, want agent_protocol", err)
			}
		})
	}
}

func TestRenderReturnsTypedBusyError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusConflict)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"error": map[string]string{"code": "agent_busy", "message": "KOMPAS Renderer is busy"},
		})
	}))
	defer server.Close()
	t.Setenv("TMM_KOMPAS_RENDERER_URL", server.URL)
	client, err := New()
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.Render([]byte(`{"format":"tmm-kompas-plan"}`))
	rendererErr, ok := err.(*Error)
	if !ok || rendererErr.Status != http.StatusConflict || rendererErr.Code != "agent_busy" {
		t.Fatalf("busy error = %#v, want agent_busy", err)
	}
}

func TestNewRejectsUnreachableRendererURLs(t *testing.T) {
	for _, value := range []string{
		"http://example.com:17342",
		"http://127.0.0.2:17342",
		"http://[::1]:17342",
	} {
		t.Run(value, func(t *testing.T) {
			t.Setenv("TMM_KOMPAS_RENDERER_URL", value)
			if _, err := New(); err == nil {
				t.Fatalf("New accepted unreachable renderer URL %q", value)
			}
		})
	}
}

func TestGetCapabilitiesReturnsUnavailableError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	url := server.URL
	server.Close()
	t.Setenv("TMM_KOMPAS_RENDERER_URL", url)
	client, err := New()
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.GetCapabilities()
	rendererErr, ok := err.(*Error)
	if !ok || rendererErr.Code != "agent_unavailable" {
		t.Fatalf("unavailable error = %#v", err)
	}
}

func TestClientDoesNotFollowRendererRedirect(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "https://example.com/secret", http.StatusTemporaryRedirect)
	}))
	defer server.Close()
	t.Setenv("TMM_KOMPAS_RENDERER_URL", server.URL)
	client, err := New()
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.GetCapabilities()
	rendererErr, ok := err.(*Error)
	if !ok || rendererErr.Status != http.StatusTemporaryRedirect {
		t.Fatalf("redirect error = %#v", err)
	}
}
