FROM node:20-alpine AS build

# VITE_API_BASE is injected at build time so the browser knows the backend URL
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=${VITE_API_BASE}

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
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80
