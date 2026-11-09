/**
 * Clew — PM2 ecosystem config
 *
 * Manages four processes on the production EC2 instance:
 *   clew-api       FastAPI (Uvicorn, 2 workers)
 *   clew-frontend  Next.js (next start)
 *   clew-worker    Celery worker (log ingestion + blocking tasks)
 *   clew-beat      Celery beat scheduler (polls S3 every 15 min)
 *
 * Usage:
 *   pm2 start ecosystem.config.js
 *   pm2 save && pm2 startup   (persist across reboots)
 *   pm2 status                (check all processes)
 *   pm2 logs clew-api --lines 50
 */

module.exports = {
  apps: [
    // ─────────────────────────────────────────────────────────────────────
    // FastAPI — serves all /api and /auth routes
    // ─────────────────────────────────────────────────────────────────────
    {
      name: 'clew-api',
      cwd: '/home/ubuntu/abuse',
      interpreter: '/home/ubuntu/abuse/.venv/bin/python',
      script: '/home/ubuntu/abuse/.venv/bin/uvicorn',
      args: 'api.main:app --host 127.0.0.1 --port 8000 --workers 2',
      env_file: '/home/ubuntu/abuse/.env',
      // Restart on crash, wait 5 s before restart
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
    },

    // ─────────────────────────────────────────────────────────────────────
    // Next.js — serves the marketing site + dashboard
    // ─────────────────────────────────────────────────────────────────────
    {
      name: 'clew-frontend',
      cwd: '/home/ubuntu/abuse/frontend',
      script: 'node_modules/.bin/next',
      args: 'start --port 3000',
      env: {
        NODE_ENV: 'production',
        // Browser calls the API same-origin at /api (nginx maps it to FastAPI).
        NEXT_PUBLIC_API_URL: '/api',
        NEXT_PUBLIC_SITE_URL: 'https://www.clewsec.com',
        NEXT_PUBLIC_DASHBOARD_URL: 'https://dashboard.clewsec.com',
        // Server-side only (read by the Next.js proxy).
        DASHBOARD_HOST: 'dashboard.clewsec.com',
        // Phase 6 staff ops panel: /internal pages are served only on this host.
        INTERNAL_HOST: 'internal.clewsec.com',
        HOME_URL: 'https://www.clewsec.com',
        API_INTERNAL_URL: 'http://127.0.0.1:8000',
      },
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
    },

    // ─────────────────────────────────────────────────────────────────────
    // Celery worker — executes process_logs, push_block, send_alerts tasks
    // ─────────────────────────────────────────────────────────────────────
    {
      name: 'clew-worker',
      cwd: '/home/ubuntu/abuse',
      interpreter: '/home/ubuntu/abuse/.venv/bin/python',
      script: '/home/ubuntu/abuse/.venv/bin/celery',
      args: '-A workers.celery_app worker --loglevel=info --concurrency=4',
      env_file: '/home/ubuntu/abuse/.env',
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
    },

    // ─────────────────────────────────────────────────────────────────────
    // Celery beat — triggers poll_all_clients every 15 minutes
    // Only one beat process should ever run — it is the scheduler, not a
    // worker. Running two would double-schedule every task.
    // ─────────────────────────────────────────────────────────────────────
    {
      name: 'clew-beat',
      cwd: '/home/ubuntu/abuse',
      interpreter: '/home/ubuntu/abuse/.venv/bin/python',
      script: '/home/ubuntu/abuse/.venv/bin/celery',
      args: '-A workers.celery_app beat --loglevel=info',
      env_file: '/home/ubuntu/abuse/.env',
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
    },
  ],
};
