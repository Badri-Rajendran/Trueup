# Multi-stage build: `npm run build` needs the full node_modules tree; the runtime stage ships
# only the static `dist/` output plus a tiny nginx, never the toolchain.

FROM node:22-alpine AS builder

WORKDIR /app

# Dependencies first, from the lockfile alone, so an application-code change never invalidates
# this layer.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
# The official nginx image's own entrypoint (`/docker-entrypoint.d/20-envsubst-on-templates.sh`)
# renders any `*.template` file here into `/etc/nginx/conf.d/`, substituting only variables that
# are actually set in the container's environment -- nginx's own `$host`/`$remote_addr`/etc. are
# never OS environment variables, so they pass through untouched automatically.
COPY nginx.conf.template /etc/nginx/templates/nginx.conf.template

# Default matches docker-compose's network; a deployed environment (e.g. Azure Container Apps)
# overrides this to the backend's actual reachable address -- see the module comment in
# nginx.conf.template for why this can't stay hardcoded.
ENV BACKEND_URL=http://backend:8000

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
