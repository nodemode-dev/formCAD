import { events } from '../../io/events';
import { out, type PlotJob } from './output-api';

let serial = 0;

function post(id: string, state: string, label: string, message = '', progress?: number): void {
  events.inject({ type: 'job', id, label, state, message, ...(progress === undefined ? {} : { progress }) });
}

export async function trackWork<T>(label: string, work: () => Promise<T>): Promise<T> {
  const id = `ui-${Date.now().toString(36)}-${serial++}`;
  post(id, 'running', label);
  try {
    const value = await work();
    post(id, 'done', label);
    return value;
  } catch (e) {
    post(id, 'failed', label, e instanceof Error ? e.message : 'The job failed');
    throw e;
  }
}

export async function followJob(job: PlotJob, label: string): Promise<PlotJob> {
  const id = `plot-${job.id}`;
  let cur = job;
  post(id, 'running', label);
  for (let i = 0; cur.state === 'queued' || cur.state === 'running'; i++) {
    await new Promise((r) => window.setTimeout(r, i < 5 ? 120 : 400));
    try {
      cur = await out.job(job.id);
    } catch (e) {
      post(id, 'failed', label, e instanceof Error ? e.message : 'The job could not be read');
      throw e;
    }
  }
  post(id, cur.state === 'done' ? 'done' : 'failed', label, cur.message);
  return cur;
}
