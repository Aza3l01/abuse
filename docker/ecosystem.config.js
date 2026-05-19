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
      cwd: '/home/ubuntu/clew',
      interpreter: '/home/ubuntu/clew/.venv/bin/python',
      script: '/home/ubuntu/clew/.venv/bin/uvicorn',
      args: 'api.main:app --host 127.0.0.1 --port 8000 --workers 2',
      env_file: '/home/ubuntu/clew/.env',
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
      cwd: '/home/ubuntu/clew/frontend',
      script: 'node_modules/.bin/next',
      args: 'start --port 3000',
      env: {
        NODE_ENV: 'production',
        NEXT_PUBLIC_API_URL: 'https://api.yourdomain.com',
        NEXT_PUBLIC_SITE_URL: 'https://yourdomain.com',
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
      cwd: '/home/ubuntu/clew',
      interpreter: '/home/ubuntu/clew/.venv/bin/python',
      script: '/home/ubuntu/clew/.venv/bin/celery',
      args: '-A workers.celery_app worker --loglevel=info --concurrency=4',
      env_file: '/home/ubuntu/clew/.env',
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
      cwd: '/home/ubuntu/clew',
      interpreter: '/home/ubuntu/clew/.venv/bin/python',
      script: '/home/ubuntu/clew/.venv/bin/celery',
      args: '-A workers.celery_app beat --loglevel=info',
      env_file: '/home/ubuntu/clew/.env',
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
    },
  ],
};
