FROM node:20-alpine AS build

# Keep backward compatibility with the old VITE_API_BASE while supporting
# the same API/OIDC variable names used by the nguyenvantuan source.
ARG VITE_API_URL=/api
ARG VITE_API_BASE_URL=${VITE_API_URL}
ARG VITE_API_BASE=${VITE_API_BASE_URL}
ARG VITE_OIDC_ISSUER=https://api.etechs.vn
ARG VITE_OIDC_CLIENT_ID=ers-fe
ARG VITE_OIDC_REDIRECT_URI=https://ers.etechs.vn/auth/callback
ARG VITE_OIDC_POST_LOGOUT_REDIRECT_URI=https://ers.etechs.vn
ARG VITE_OIDC_SCOPE="openid profile email"

ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_API_BASE=${VITE_API_BASE}
ENV VITE_OIDC_ISSUER=${VITE_OIDC_ISSUER}
ENV VITE_OIDC_CLIENT_ID=${VITE_OIDC_CLIENT_ID}
ENV VITE_OIDC_REDIRECT_URI=${VITE_OIDC_REDIRECT_URI}
ENV VITE_OIDC_POST_LOGOUT_REDIRECT_URI=${VITE_OIDC_POST_LOGOUT_REDIRECT_URI}
ENV VITE_OIDC_SCOPE=${VITE_OIDC_SCOPE}

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# --- Production stage: nginx serves the static build ---
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

# Simple nginx config: serve SPA, fallback to index.html for client-side routing
RUN printf 'server {\n\
    listen 80;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
\n\
    location /api/ {\n\
        proxy_pass http://backend:8000/;\n\
        proxy_http_version 1.1;\n\
        proxy_set_header Host $host;\n\
        proxy_set_header X-Real-IP $remote_addr;\n\
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n\
        proxy_set_header X-Forwarded-Proto $scheme;\n\
    }\n\
\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80
