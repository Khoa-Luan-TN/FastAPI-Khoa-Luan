import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearAppSession,
  clearOidcRequestStorage,
  exchangeAuthorizationCode,
  exchangeOidcTokenForAppJwt,
  getOidcRequestContext,
  storeAppSession,
} from "../services/oidcService";
import "../styles/login.css";

export default function AuthCallback() {
  const navigate = useNavigate();
  const [error, setError] = useState("");

  useEffect(() => {
    const runCallback = async () => {
      try {
        const params = new URLSearchParams(window.location.search);
        const code = params.get("code");
        const state = params.get("state");
        const oidcError = params.get("error");
        const requestContext = getOidcRequestContext();

        if (oidcError) {
          throw new Error(params.get("error_description") || oidcError);
        }

        if (!code) {
          throw new Error("Thiếu authorization code từ SSO callback");
        }

        if (!requestContext.codeVerifier || !requestContext.expectedState) {
          throw new Error("Không tìm thấy phiên đăng nhập SSO trước đó. Vui lòng thử lại.");
        }

        if (!state || state !== requestContext.expectedState) {
          throw new Error("State không hợp lệ, vui lòng đăng nhập lại.");
        }

        const oidcToken = await exchangeAuthorizationCode(code, requestContext.codeVerifier);
        const oidcAccessToken = oidcToken.access_token || oidcToken.id_token;

        if (!oidcAccessToken) {
          throw new Error("Không nhận được access_token hoặc id_token từ OIDC.");
        }

        const exchangeResponse = await exchangeOidcTokenForAppJwt(oidcAccessToken);
        const exchangeUser = exchangeResponse?.user || {};

        storeAppSession({
          user: exchangeUser,
          access: exchangeResponse?.access,
          refresh: exchangeResponse?.refresh,
        });

        clearOidcRequestStorage();

        const role = String(exchangeUser?.role || "user").toLowerCase();
        const fallbackPath = role === "admin" ? "/admin" : "/user";
        const redirectTo = requestContext.redirectAfterLogin || fallbackPath;
        navigate(redirectTo === "/" ? fallbackPath : redirectTo, { replace: true });
      } catch (callbackError) {
        console.error("OIDC callback error:", callbackError);
        clearAppSession();
        setError(callbackError?.message || "Đăng nhập SSO thất bại");
      }
    };

    runCallback();
  }, [navigate]);

  return (
    <div className="login-page">
      <div className="background-image"></div>
      <div className="login-container">
        <div className="login-card">
          <div className="header">
            <div className="brand-kicker">Etechs.vn</div>
            <h1 className="brand-title">{error ? "Đăng nhập thất bại" : "Đang xử lý đăng nhập SSO..."}</h1>
            <p className="brand-subtitle">
              {error
                ? "Phiên đăng nhập không thể hoàn tất. Vui lòng quay lại và thử lại."
                : "Hệ thống đang hoàn tất xác thực và thiết lập phiên làm việc của bạn."}
            </p>
          </div>

          {error && (
            <div className="error-message">
              <span className="error-icon">!</span>
              <span>{error}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
