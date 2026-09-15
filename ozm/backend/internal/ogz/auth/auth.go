package auth

import (
	"context"
	"net/http"
	"strings"
)

// Principal is the authenticated caller derived from the SSO token.
type Principal struct {
	Sub        string
	PortalCode string
}

type ctxKey string

const principalKey ctxKey = "principal"

// Authenticator verifies inbound credentials. Full OIDC discovery + JWKS
// verification (tnlife-integration §3.2) lands in a later iteration; dev mode
// short-circuits to a deterministic principal for local work only.
type Authenticator struct {
	devMode bool
}

func New(devMode bool) *Authenticator { return &Authenticator{devMode: devMode} }

func (a *Authenticator) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		tok := bearer(r)
		if tok == "" {
			unauthorized(w)
			return
		}
		var p Principal
		if a.devMode {
			p = Principal{Sub: "dev-" + tok, PortalCode: "dev"}
		} else {
			// TODO(SEC): OIDC discovery (fail-closed) + JWKS verification.
			unauthorized(w)
			return
		}
		ctx := context.WithValue(r.Context(), principalKey, p)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// PrincipalFrom returns the authenticated principal from context.
func PrincipalFrom(ctx context.Context) (Principal, bool) {
	p, ok := ctx.Value(principalKey).(Principal)
	return p, ok
}

func bearer(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if strings.HasPrefix(h, "Bearer ") {
		return strings.TrimSpace(strings.TrimPrefix(h, "Bearer "))
	}
	return ""
}

func unauthorized(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusUnauthorized)
	_, _ = w.Write([]byte(`{"error":"unauthorized"}`))
}
