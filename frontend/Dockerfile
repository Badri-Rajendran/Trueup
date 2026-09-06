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
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
