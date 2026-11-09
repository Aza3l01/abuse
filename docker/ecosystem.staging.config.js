/**
 * Clew: PM2 ecosystem config for STAGING (same EC2 server as production)
 *
 * A separate checkout at /home/ubuntu/abuse-staging with its own .env (see
 * .env.staging.example). Every process name carries the clew-stg prefix so a
 * `pm2 restart all` typed for production never has to be confused with this
 * stack, and so nothing here can collide with the production processes.
 *
 *   clew-stg-api       FastAPI on 127.0.0.1:8100 (production uses 8000)
 *   clew-stg-frontend  Next.js on :3100 (production uses 3000)
 *   clew-stg-worker    Celery worker, Redis database index 1
 *   clew-stg-beat      Celery beat, its own schedule file in the staging checkout
 *
 * Usage:
 *   pm2 start docker/ecosystem.staging.config.js
 *   pm2 save
 *   pm2 logs clew-stg-api --lines 50
 */

const ROOT = '/home/ubuntu/abuse-staging';

module.exports = {
  apps: [
    {
      name: 'clew-stg-api',
      cwd: ROOT,
      interpreter: `${ROOT}/.venv/bin/python`,
      script: `${ROOT}/.venv/bin/uvicorn`,
      args: 'api.main:app --host 127.0.0.1 --port 8100 --workers 1',
      env_file: `${ROOT}/.env`,
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
    },

    {
      name: 'clew-stg-frontend',
      cwd: `${ROOT}/frontend`,
      script: 'node_modules/.bin/next',
      args: 'start --port 3100',
      env: {
        NODE_ENV: 'production',
        NEXT_PUBLIC_API_URL: '/api',
        NEXT_PUBLIC_SITE_URL: 'https://stg.clewsec.com',
        NEXT_PUBLIC_DASHBOARD_URL: 'https://stg-dashboard.clewsec.com',
        // Server-side only (read by the Next.js proxy).
        DASHBOARD_HOST: 'stg-dashboard.clewsec.com',
        INTERNAL_HOST: 'stg-internal.clewsec.com',
        HOME_URL: 'https://stg.clewsec.com',
        API_INTERNAL_URL: 'http://127.0.0.1:8100',
      },
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
    },

    {
      name: 'clew-stg-worker',
      cwd: ROOT,
      interpreter: `${ROOT}/.venv/bin/python`,
      script: `${ROOT}/.venv/bin/celery`,
      args: '-A workers.celery_app worker --loglevel=info --concurrency=2',
      env_file: `${ROOT}/.env`,
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
    },

    // Only one beat per stack. Staging has its own checkout, so it also has its
    // own celerybeat-schedule file; never point this at the production one.
    {
      name: 'clew-stg-beat',
      cwd: ROOT,
      interpreter: `${ROOT}/.venv/bin/python`,
      script: `${ROOT}/.venv/bin/celery`,
      args: `-A workers.celery_app beat --loglevel=info --schedule ${ROOT}/celerybeat-schedule`,
      env_file: `${ROOT}/.env`,
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
    },
  ],
};
