# Production image of the AuraCinema website: the built React app served by
# Caddy, which also forwards /api requests to the API container.
# Build context: the frontend folder (see backend/docker-compose.yml, service "web").

# --- Stage 1: build the static files (HTML, CSS, JavaScript) with Node ------------
FROM node:24-alpine AS build
WORKDIR /app

# Install dependencies first so this layer is cached between code changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Relative address: the website and the API share one origin behind Caddy,
# so the browser calls the API "at home" and CORS does not apply.
ENV VITE_API_BASE_URL=/api/v1
RUN npm run build

# --- Stage 2: serve them with Caddy (Node is not part of the final image) ---------
FROM caddy:2.10-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
