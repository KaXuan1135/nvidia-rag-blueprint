FROM node:24-bookworm-slim

WORKDIR /app
COPY index.html styles.css app.js server.js ./

ENV NODE_ENV=production
EXPOSE 3000

CMD ["node", "server.js"]
