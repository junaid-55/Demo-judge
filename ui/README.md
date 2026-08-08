# Chakrikoi Netlify UI

This is a static browser UI. Netlify serves these files; it never runs the judge or stores source code.

## Deploy

Create a Netlify site with `ui` as the base directory. Netlify reads `netlify.toml` from that directory and publishes the directory without a build command.

For a local preview, serve this directory through any static file server. Do not open `index.html` with a `file://` URL because the local runner checks browser origins.

## Local demo setup

1. Start the backend: `cd ../backend_draft && docker compose up --build --detach`.
2. Build the agent after source changes: `cd ../source && ./build.sh`.
3. Start the generated local agent: `cd ../user_agent && ./chakrikoi-runner --bootstrap bootstrap.json`.
4. Open the deployed Netlify page and press **Connect**. The default agent address is `http://127.0.0.1:37123`.

The browser reads the public problem catalog directly from the backend and sends source only to the loopback agent. The agent obtains the signed grant, fetches private test data, starts Docker, and sends the one final completion request to the backend. Source code and private expected output are not sent from Netlify to the backend directly. SQL problems use a reusable local PostgreSQL container that is released when the user leaves the problem.

## Netlify and loopback requirements

The backend compose file allows `https://*.netlify.app` through the runner manifest for this demo. Before a real release, replace that wildcard with the exact deployed UI origin. Browsers can require permission to access a local network service from a public HTTPS page; approve the browser prompt if it appears. Keep the agent bound to loopback only, as it is now.
