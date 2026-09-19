FROM node:22-alpine AS build
WORKDIR /srv/web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production PORT=8080 API_UPSTREAM=http://api:8080
WORKDIR /srv/web
COPY --from=build /srv/web/dist ./dist
COPY server.mjs ./server.mjs
USER node
EXPOSE 8080
CMD ["node", "server.mjs"]
