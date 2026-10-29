FROM node:22-bookworm-slim AS build

WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist/ /usr/share/nginx/html/
COPY LICENSE /usr/share/nginx/html/LICENSE
EXPOSE 80
