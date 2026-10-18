# PAM frontend — SPEC §8 M15: node build → nginx. No secrets are baked into the bundle.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vite inlines VITE_* values from .env files; none of them may reach the image.
RUN rm -f .env .env.* && npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
