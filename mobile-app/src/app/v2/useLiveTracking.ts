/**
 * Live position for a viewer (spec §10.3 step 5): the K8 WebSocket pushes the snapshot every few seconds; while the
 * socket is not open the HTTP snapshot (K4 / K7) is polled every 15 s, and the socket is retried with a backoff.
 *
 * The server re-checks the viewer and the tracking window on every push, so this hook trusts only what arrives: it
 * never moves a marker on its own. Close codes: 4401 auth (one retry after the HTTP call refreshes the token),
 * 4403 window closed (polling only, the socket is retried once the window opens), 4404 unknown or revoked.
 */
import { useEffect, useRef, useState } from "react";

import { trackingWebSocketUrl } from "../../api/v2/tracking.api";
import { ApiError } from "../../types/api";

export const POLL_INTERVAL_MS = 15_000;
const RECONNECT_BASE_MS = 5_000;
const RECONNECT_MAX_MS = 60_000;

export type LiveTransport = "idle" | "ws" | "poll";

type SocketLike = Pick<WebSocket, "send" | "close"> & {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
};

export type LiveTrackingOptions<T> = {
  /** Booking id or tracking token; `null` switches the hook off. */
  subject: string | null;
  enabled?: boolean;
  fetchSnapshot: () => Promise<T>;
  subscribeFrame: () => Record<string, unknown>;
  /** Whether a polled snapshot says the window is open (then the socket is worth another try). */
  windowOpen: (data: T) => boolean;
  initial?: T | null;
  socketFactory?: ((url: string) => SocketLike) | null;
};

export type LiveTrackingState<T> = {
  data: T | null;
  error: unknown;
  transport: LiveTransport;
  /** The server said this subject is not (or no longer) visible to this viewer. */
  gone: boolean;
};

function defaultSocketFactory(): ((url: string) => SocketLike) | null {
  return typeof WebSocket === "undefined" ? null : (url) => new WebSocket(url) as unknown as SocketLike;
}

export function useLiveTracking<T>(options: LiveTrackingOptions<T>): LiveTrackingState<T> {
  const { subject, enabled = true } = options;
  const [data, setData] = useState<T | null>(options.initial ?? null);
  const [error, setError] = useState<unknown>(null);
  const [transport, setTransport] = useState<LiveTransport>("idle");
  const [gone, setGone] = useState(false);
  const latest = useRef(options);
  latest.current = options;

  useEffect(() => {
    if (!subject || !enabled) {
      setTransport("idle");
      return;
    }
    let disposed = false;
    let socket: SocketLike | null = null;
    let pollTimer: number | undefined;
    let reconnectTimer: number | undefined;
    let attempts = 0;
    let authRetried = false;
    let windowClosed = false;
    // While the socket delivers, a slower HTTP answer is older news: it must not move the marker back.
    let socketLive = false;
    const factory = latest.current.socketFactory === undefined ? defaultSocketFactory() : latest.current.socketFactory;

    const stopPolling = () => {
      if (pollTimer !== undefined) window.clearInterval(pollTimer);
      pollTimer = undefined;
    };

    const finish = () => {
      disposed = true;
      stopPolling();
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      const current = socket;
      socket = null;
      if (current) {
        current.onclose = null;
        current.onerror = null;
        current.onmessage = null;
        current.close();
      }
    };

    const poll = async () => {
      try {
        const value = await latest.current.fetchSnapshot();
        if (disposed || socketLive) return;
        setData(value);
        setError(null);
        // The window opened while we were polling: the socket is worth another try.
        if (windowClosed && latest.current.windowOpen(value) && !socket && reconnectTimer === undefined) {
          windowClosed = false;
          connect();
        }
      } catch (cause) {
        if (disposed) return;
        if (cause instanceof ApiError && cause.status === 404) {
          setGone(true);
          finish();
          setTransport("idle");
          return;
        }
        setError(cause);
      }
    };

    const startPolling = () => {
      setTransport("poll");
      if (pollTimer === undefined) pollTimer = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    };

    const scheduleReconnect = () => {
      if (disposed || reconnectTimer !== undefined) return;
      const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** attempts);
      attempts += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = undefined;
        connect();
      }, delay);
    };

    function connect() {
      if (disposed || !factory) return;
      let opened: SocketLike;
      try {
        opened = factory(trackingWebSocketUrl());
      } catch {
        startPolling();
        return;
      }
      socket = opened;
      opened.onopen = () => opened.send(JSON.stringify(latest.current.subscribeFrame()));
      opened.onmessage = (event) => {
        let message: { type?: string; data?: T } | null = null;
        try {
          message = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (message?.type === "tracking.point" && message.data) {
          attempts = 0;
          authRetried = false;
          socketLive = true;
          stopPolling();
          setTransport("ws");
          setData(message.data);
          setError(null);
        }
      };
      opened.onerror = () => undefined; // the close event that follows decides
      opened.onclose = (event) => {
        if (socket === opened) socket = null;
        socketLive = false;
        if (disposed) return;
        if (event.code === 4404) {
          setGone(true);
          finish();
          setTransport("idle");
          return;
        }
        startPolling();
        if (event.code === 4403) {
          windowClosed = true; // poll() reconnects once the window is open
          void poll();
          return;
        }
        if (event.code === 4401) {
          if (authRetried) return; // polling only; the HTTP layer owns the login state
          authRetried = true;
          // The HTTP call refreshes an expired access token; the retry then carries the new one.
          void poll().then(() => !disposed && connect());
          return;
        }
        scheduleReconnect();
      };
    }

    void poll();
    if (factory) connect();
    else startPolling();
    return finish;
  }, [subject, enabled]);

  return { data, error, transport, gone };
}
