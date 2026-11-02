import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';

const MAX_BODY_BYTES = 1024 * 1024;
const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 8900;

const json = (res, status, value) => {
  const body = JSON.stringify(value);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body)
  });
  res.end(body);
};

const clone = (value) => JSON.parse(JSON.stringify(value));

async function loadFixtures(source) {
  if (source && typeof source === 'object') return clone(source);
  const file = typeof source === 'string'
    ? source
    : resolve(dirname(new URL(import.meta.url).pathname), 'fixtures.json');
  return JSON.parse(await readFile(file, 'utf8'));
}

function policyForModel(org, model) {
  const [id, requestedVersion] = model.split('@', 2);
  const policy = org.policies.find((candidate) => candidate.id === id);
  if (!policy || (requestedVersion !== undefined && requestedVersion !== policy.version)) return undefined;
  return policy;
}

function scoreFor(policy, text) {
  const lower = text.toLocaleLowerCase();
  if ((policy.keywords ?? []).some((keyword) => lower.includes(keyword.toLocaleLowerCase()))) return 0.95;
  if ((policy.mediumKeywords ?? []).some((keyword) => lower.includes(keyword.toLocaleLowerCase()))) return 0.6;
  const digest = createHash('sha256').update(`${text}\u0000${policy.id}`).digest();
  const number = digest.readUInt32BE(0) % 1901;
  return Number((0.01 + number / 10000).toFixed(4));
}

function validString(value) {
  return typeof value === 'string' && value.length > 0 && !value.includes('\u0000');
}

function validateClassify(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return 'request body must be an object';
  if (!validString(body.model)) return 'model must be a non-empty string';
  if (!body.input || typeof body.input !== 'object' || Array.isArray(body.input)) {
    return 'input must be an object';
  }
  if (body.input.text !== undefined && typeof body.input.text !== 'string') return 'input.text must be a string';
  if (body.input.mediaUrl !== undefined && typeof body.input.mediaUrl !== 'string') return 'input.mediaUrl must be a string';
  if (body.policy !== undefined && typeof body.policy !== 'string') return 'policy must be a string';
  if (body.input.text === undefined && body.input.mediaUrl === undefined) return 'input.text or input.mediaUrl is required';
  return undefined;
}

function tokenOrg(req, fixtures) {
  const header = req.headers.authorization;
  if (typeof header !== 'string' || !header.startsWith('Bearer ')) return undefined;
  const token = header.slice('Bearer '.length);
  const orgId = fixtures.tokens?.[token];
  return typeof orgId === 'string' ? orgId : undefined;
}

async function readJson(req) {
  return new Promise((resolveBody, reject) => {
    let size = 0;
    let tooLarge = false;
    const chunks = [];
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        tooLarge = true;
        return;
      }
      if (!tooLarge) chunks.push(chunk);
    });
    req.on('end', () => {
      if (tooLarge) {
        reject(Object.assign(new Error('request body too large'), { status: 413 }));
        return;
      }
      try {
        resolveBody(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch {
        reject(Object.assign(new Error('invalid JSON body'), { status: 422 }));
      }
    });
    req.on('error', reject);
  });
}

function logRequest(req, status) {
  console.log(`${req.method} ${req.url} ${status}`);
}

export async function startMockServer({ port = DEFAULT_PORT, host = DEFAULT_HOST, fixtures } = {}) {
  let state = await loadFixtures(fixtures);
  const server = createServer(async (req, res) => {
    let status = 500;
    const finish = (code, value) => {
      status = code;
      json(res, code, value);
    };
    try {
      const url = new URL(req.url ?? '/', `http://${req.headers.host ?? host}`);
      if (req.method === 'GET' && url.pathname === '/health') {
        finish(200, { status: 'ok' });
      } else if (req.method === 'POST' && url.pathname === '/__mock/reset') {
        state = await loadFixtures(fixtures);
        status = 204;
        res.writeHead(204);
        res.end();
      } else if (url.pathname.startsWith('/v1/') || url.pathname.startsWith('/__mock/')) {
        const orgId = tokenOrg(req, state);
        if (!orgId || !state.orgs?.[orgId]) {
          finish(401, { detail: 'invalid or missing bearer token' });
        } else if (req.method === 'GET' && url.pathname === '/v1/policies') {
          finish(200, {
            policies: state.orgs[orgId].policies.map(({ id, version, base, display }) => ({
              id, version: String(version), base, display
            }))
          });
        } else if (req.method === 'DELETE' && url.pathname.startsWith('/__mock/policies/')) {
          const id = decodeURIComponent(url.pathname.slice('/__mock/policies/'.length));
          const policies = state.orgs[orgId].policies;
          const index = policies.findIndex((policy) => policy.id === id);
          if (index < 0) finish(404, { detail: `unknown policy '${id}'` });
          else {
            policies.splice(index, 1);
            status = 204;
            res.writeHead(204);
            res.end();
          }
        } else if (req.method === 'POST' && url.pathname === '/v1/classify') {
          const body = await readJson(req);
          const error = validateClassify(body);
          if (error) finish(422, { detail: error });
          else {
            const policy = policyForModel(state.orgs[orgId], body.model);
            if (!policy) finish(404, { detail: `unknown model '${body.model}'` });
            else if (body.input.mediaUrl !== undefined) {
              finish(422, { detail: `model '${policy.id}': image input is not yet supported for chat/BYOP models` });
            } else {
              finish(200, {
                model: `${policy.id}@${policy.version}`,
                results: [{ label: 'verdict', score: scoreFor(policy, body.input.text) }]
              });
            }
          }
        } else if (req.method === 'POST' && url.pathname === '/v1/policies') {
          const body = await readJson(req);
          if (!body || typeof body !== 'object' || Array.isArray(body)) finish(422, { detail: 'request body must be an object' });
          else if (!validString(body.name) || !validString(body.policyText)) finish(422, { detail: 'name and policyText must be non-empty strings' });
          else {
            const bases = new Set(Object.values(state.orgs).flatMap((org) => org.policies.map((policy) => policy.base)));
            if (!validString(body.base) || !bases.has(body.base)) {
              finish(422, { detail: `base '${body.base ?? ''}' is not a policy-steerable (BYOP) model spec` });
            } else if (body.display !== undefined && typeof body.display !== 'string') {
              finish(422, { detail: 'display must be a string' });
            } else {
              const policies = state.orgs[orgId].policies;
              const existing = policies.find((policy) => policy.id === body.name);
              const policy = {
                id: body.name,
                version: String(Number(existing?.version ?? 0) + 1),
                base: body.base,
                display: body.display || body.name,
                keywords: existing?.keywords ?? [],
                mediumKeywords: existing?.mediumKeywords ?? []
              };
              if (existing) Object.assign(existing, policy);
              else policies.push(policy);
              finish(200, { id: policy.id, version: policy.version, base: policy.base, display: policy.display });
            }
          }
        } else {
          finish(404, { detail: 'not found' });
        }
      } else {
        finish(404, { detail: 'not found' });
      }
    } catch (error) {
      finish(error?.status === 413 ? 413 : 422, { detail: error?.status === 413 ? error.message : 'invalid request' });
    } finally {
      logRequest(req, status);
    }
  });
  await new Promise((resolveListen, reject) => {
    server.once('error', reject);
    server.listen(port, host, resolveListen);
  });
  const address = server.address();
  const actualPort = typeof address === 'object' && address ? address.port : port;
  return {
    url: `http://${host}:${actualPort}`,
    server,
    close: () => new Promise((resolveClose, rejectClose) => server.close((error) => error ? rejectClose(error) : resolveClose()))
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const instance = await startMockServer({
    port: Number(process.env.PORT ?? DEFAULT_PORT),
    host: process.env.HOST ?? DEFAULT_HOST,
    fixtures: process.env.PIGEON_MOCK_FIXTURES ?? undefined
  });
  console.log(`Pigeon mock server listening at ${instance.url}`);
  const shutdown = async () => {
    await instance.close();
    process.exit(0);
  };
  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
}
