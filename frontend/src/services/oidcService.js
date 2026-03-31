const OIDC_SCOPE = import.meta.env.VITE_OIDC_SCOPE || "openid profile email";
const OIDC_ISSUER = (import.meta.env.VITE_OIDC_ISSUER || "https://api.etechs.vn").replace(/\/$/, "");
const OIDC_CLIENT_ID = import.meta.env.VITE_OIDC_CLIENT_ID || "ers-fe";
const OIDC_REDIRECT_URI =
  import.meta.env.VITE_OIDC_REDIRECT_URI || `${window.location.origin}/auth/callback`;
const OIDC_POST_LOGOUT_REDIRECT_URI =
  import.meta.env.VITE_OIDC_POST_LOGOUT_REDIRECT_URI || window.location.origin;

const storageKeys = {
  verifier: "oidc_code_verifier",
  state: "oidc_state",
  nonce: "oidc_nonce",
  redirectAfterLogin: "oidc_redirect_after_login",
  access: "app_access_token",
  refresh: "app_refresh_token",
};

const randomString = (length = 64) => {
  const charset = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
  const randomValues = new Uint8Array(length);
  crypto.getRandomValues(randomValues);
  return Array.from(randomValues)
    .map((value) => charset[value % charset.length])
    .join("");
};

const base64UrlEncode = (input) => {
  const bytes = new Uint8Array(input);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

const sha256 = async (plainText) => {
  const encoder = new TextEncoder();
  return crypto.subtle.digest("SHA-256", encoder.encode(plainText));
};

const parseJsonSafe = async (response) => {
  try {
    return await response.json();
  } catch {
    return null;
  }
};

const prepareOidcAuthorizeRequest = async (redirectAfterLogin = "/user") => {
  const codeVerifier = randomString(96);
  const codeChallenge = base64UrlEncode(await sha256(codeVerifier));
  const state = randomString(32);
  const nonce = randomString(32);

  sessionStorage.setItem(storageKeys.verifier, codeVerifier);
  sessionStorage.setItem(storageKeys.state, state);
  sessionStorage.setItem(storageKeys.nonce, nonce);
  sessionStorage.setItem(storageKeys.redirectAfterLogin, redirectAfterLogin);

  return {
    client_id: OIDC_CLIENT_ID,
    redirect_uri: OIDC_REDIRECT_URI,
    response_type: "code",
    scope: OIDC_SCOPE,
    state,
    nonce,
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
  };
};

export const resolveOidcRedirectUrl = (redirectUrl) => {
  if (!redirectUrl) {
    throw new Error("Thiếu redirect_url từ middleware OIDC");
  }

  try {
    return new URL(redirectUrl).toString();
  } catch {
    return new URL(redirectUrl, `${OIDC_ISSUER}/`).toString();
  }
};

export const loginViaOidcMiddleware = async ({ email, password, redirectAfterLogin = "/user" }) => {
  const authorizeRequest = await prepareOidcAuthorizeRequest(redirectAfterLogin);
  const response = await fetch(`${OIDC_ISSUER}/api/oidc/login/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "include",
    body: JSON.stringify({
      email,
      username: email,
      password,
      ...authorizeRequest,
    }),
  });

  const jsonData = await parseJsonSafe(response);
  if (!response.ok) {
    throw new Error(
      jsonData?.detail || jsonData?.message || jsonData?.error || "Đăng nhập SSO thất bại"
    );
  }

  return jsonData || {};
};

export const getOidcRequestContext = () => ({
  codeVerifier: sessionStorage.getItem(storageKeys.verifier),
  expectedState: sessionStorage.getItem(storageKeys.state),
  nonce: sessionStorage.getItem(storageKeys.nonce),
  redirectAfterLogin: sessionStorage.getItem(storageKeys.redirectAfterLogin) || "/user",
});

export const clearOidcRequestStorage = () => {
  sessionStorage.removeItem(storageKeys.verifier);
  sessionStorage.removeItem(storageKeys.state);
  sessionStorage.removeItem(storageKeys.nonce);
  sessionStorage.removeItem(storageKeys.redirectAfterLogin);
};

export const exchangeAuthorizationCode = async (code, codeVerifier) => {
  const payload = new URLSearchParams();
  payload.set("grant_type", "authorization_code");
  payload.set("client_id", OIDC_CLIENT_ID);
  payload.set("redirect_uri", OIDC_REDIRECT_URI);
  payload.set("code", code);
  payload.set("code_verifier", codeVerifier);

  const response = await fetch(`${OIDC_ISSUER}/api/oidc/token/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: payload.toString(),
  });

  if (!response.ok) {
    throw new Error((await response.text()) || "Đổi authorization code thất bại");
  }

  return response.json();
};

export const exchangeOidcTokenForAppJwt = async (oidcAccessToken) => {
  const response = await fetch(`${OIDC_ISSUER}/api/oidc/exchange/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      access_token: oidcAccessToken,
      client_id: OIDC_CLIENT_ID,
    }),
  });

  if (!response.ok) {
    throw new Error((await response.text()) || "Đổi OIDC token sang app JWT thất bại");
  }

  return response.json();
};

export const storeAppSession = ({ user, access, refresh }) => {
  const normalizedRole = String(user?.role || "user").toLowerCase();
  localStorage.setItem("role", normalizedRole === "admin" ? "admin" : "user");
  localStorage.setItem("user_id", String(user?.id || user?.user_id || ""));
  localStorage.setItem(
    "username",
    String(user?.username || user?.email || user?.name || user?.full_name || "SSO User")
  );

  if (access) {
    localStorage.setItem(storageKeys.access, access);
  }
  if (refresh) {
    localStorage.setItem(storageKeys.refresh, refresh);
  }
};

export const clearAppSession = () => {
  localStorage.removeItem("role");
  localStorage.removeItem("user_id");
  localStorage.removeItem("username");
  localStorage.removeItem(storageKeys.access);
  localStorage.removeItem(storageKeys.refresh);
  clearOidcRequestStorage();
};

export const buildSsoLogoutUrl = () => {
  const url = new URL(`${OIDC_ISSUER}/api/oidc/logout/`);
  url.searchParams.set("client_id", OIDC_CLIENT_ID);
  url.searchParams.set("post_logout_redirect_uri", OIDC_POST_LOGOUT_REDIRECT_URI);
  return url.toString();
};
