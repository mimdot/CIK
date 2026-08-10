# Running the Dashboard

## Option 1: Direct (Recommended for Development)

```bash
cd dashboard
npm run dev
```

Then open http://localhost:3000

---

## Option 2: Docker Compose (Full Stack)

```bash
# From project root
docker-compose up dashboard
```

This runs the dashboard at http://localhost:3000 with the API backend at http://localhost:8000

---

## Notes

- The dashboard requires the API backend to be running (via `docker-compose up api` or separately)
- Environment variables are configured in `.env` and `docker-compose.yml`
- `NEXT_PUBLIC_API_URL` defaults to `http://localhost:8000`
