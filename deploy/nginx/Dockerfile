FROM node:24-alpine AS web_build
WORKDIR /srv/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ARG VITE_GOOGLE_MAPS_API_KEY=
ENV VITE_GOOGLE_MAPS_API_KEY=$VITE_GOOGLE_MAPS_API_KEY
RUN npm run build

FROM nginx:stable-alpine
COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=web_build /srv/web/dist /usr/share/nginx/html
EXPOSE 80
