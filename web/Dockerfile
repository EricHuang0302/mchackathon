FROM node:22-alpine AS build
WORKDIR /srv/web
ARG VITE_GOOGLE_MAPS_API_KEY=""
ARG VITE_GOOGLE_MAPS_MAP_ID="DEMO_MAP_ID"
ENV VITE_GOOGLE_MAPS_API_KEY=${VITE_GOOGLE_MAPS_API_KEY} \
    VITE_GOOGLE_MAPS_MAP_ID=${VITE_GOOGLE_MAPS_MAP_ID}
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
COPY rules/ /srv/rules/
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production PORT=8080 API_UPSTREAM=http://api:8080
WORKDIR /srv/web
COPY --from=build /srv/web/dist ./dist
COPY --from=build /srv/web/server.mjs ./server.mjs
USER node
EXPOSE 8080
CMD ["node", "server.mjs"]
