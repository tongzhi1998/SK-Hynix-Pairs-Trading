"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Funding = {
  current: number;
  settled: number;
  funding_time: number;
  next_funding_time: number;
};

type Leg = {
  key: string;
  label: string;
  inst_id: string;
  mark: number;
  index: number;
  basis_pct: number;
  funding: Funding;
  ts: number;
  stale: boolean;
};

type ContextMarket = {
  key: string;
  label: string;
  inst_id: string;
  mark: number | null;
  change_pct: number | null;
  proxy_note: string | null;
  ts: number;
  stale: boolean;
};

type Backfill = {
  running: boolean;
  completed: boolean;
  error: string | null;
  rows_processed: number;
};

type Snapshot = {
  as_of: number;
  source: string;
  price_type: string;
  pair: {
    korean: Leg;
    adr: Leg;
    adr_equivalent: number;
    spread: number;
    premium_pct: number;
    funding_carry: {
      long_korean_short_adr: number;
      short_korean_long_adr: number;
    };
  };
  context: ContextMarket[];
  backfill: Backfill;
};

type HistoryPoint = {
  ts: number;
  korean_mark: number;
  adr_mark: number;
  adr_equivalent: number;
  spread: number;
  premium_pct: number;
  zscore: number | null;
};

type FundingPoint = {
  ts: number;
  korean_rate: number;
  adr_rate: number;
};

type History = {
  range: string;
  bar: string;
  z_window: number;
  points: HistoryPoint[];
  funding_points: FundingPoint[];
  backfill: Backfill;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8010";
const BEIJING_TIME_ZONE = "Asia/Shanghai";
const PAIR_START_MS = 1_783_699_800_000;
const ranges = [
  ["1d", "1D"],
  ["5d", "5D"],
  ["1m", "1M"],
  ["all", "ALL"],
] as const;

function number(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

function signed(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${number(value, digits)}`;
}

function rate(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${signed(value * 100, 4)}%`;
}

function ageLabel(timestamp: number, now: number) {
  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.floor(seconds / 60)}m ago`;
}

function countdown(timestamp: number, now: number) {
  const seconds = Math.max(0, Math.floor((timestamp - now) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes.toString().padStart(2, "0")}m`;
}

function beijingClock(timestamp: number) {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: BEIJING_TIME_ZONE,
  }).format(new Date(timestamp));
}

function beijingDateTime(timestamp: number) {
  return `${new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: BEIJING_TIME_ZONE,
  }).format(new Date(timestamp)).replace(",", "")} UTC+8`;
}

type LineSeries = {
  label: string;
  values: (number | null)[];
  color: string;
  width?: number;
  markers?: boolean;
};

type ChartPoint = { ts: number };

const chartNumberFormatter = (value: number) => number(value, 2);
const chartPercentageFormatter = (value: number) => `${number(value, 1)}%`;
const chartFundingFormatter = (value: number) => `${number(value * 100, 4)}%`;
const premiumGuides = [0];

function CanvasChart({
  points,
  series,
  guides = [],
  formatter = chartNumberFormatter,
  range,
  ariaLabel,
}: {
  points: ChartPoint[];
  series: LineSeries[];
  guides?: number[];
  formatter?: (value: number) => string;
  range: string;
  ariaLabel: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hoverIndexRef = useRef<number | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || points.length < 2) return;
    const parent = canvas.parentElement;
    if (!parent) return;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const width = Math.max(320, parent.clientWidth);
      const height = Math.max(190, parent.clientHeight);
      const pixelWidth = Math.round(width * dpr);
      const pixelHeight = Math.round(height * dpr);
      if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
      if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const padding = { top: 16, right: 18, bottom: 38, left: 68 };
      const chartW = width - padding.left - padding.right;
      const chartH = height - padding.top - padding.bottom;
      const allValues = series.flatMap((line) => line.values.filter((v): v is number => v != null));
      if (!allValues.length) return;
      let min = Math.min(...allValues, ...guides);
      let max = Math.max(...allValues, ...guides);
      const margin = Math.max((max - min) * 0.1, Math.abs(max || 1) * 0.005);
      min -= margin;
      max += margin;
      const x = (index: number) => padding.left + (index / (points.length - 1)) * chartW;
      const y = (value: number) => padding.top + ((max - value) / (max - min)) * chartH;

      ctx.font = "11px var(--font-geist-mono), monospace";
      ctx.fillStyle = "#718078";
      ctx.strokeStyle = "rgba(145, 167, 155, 0.12)";
      ctx.lineWidth = 1;
      ctx.textAlign = "right";
      ctx.textBaseline = "alphabetic";
      for (let i = 0; i <= 4; i += 1) {
        const value = max - ((max - min) * i) / 4;
        const yy = padding.top + (chartH * i) / 4;
        ctx.beginPath();
        ctx.moveTo(padding.left, yy);
        ctx.lineTo(width - padding.right, yy);
        ctx.stroke();
        ctx.fillText(formatter(value), padding.left - 10, yy + 4);
      }

      guides.forEach((guide) => {
        ctx.strokeStyle = guide === 0 ? "rgba(213, 230, 220, .35)" : "rgba(249, 113, 90, .28)";
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(padding.left, y(guide));
        ctx.lineTo(width - padding.right, y(guide));
        ctx.stroke();
        ctx.setLineDash([]);
      });

      series.forEach((line) => {
        ctx.strokeStyle = line.color;
        ctx.lineWidth = line.width || 2;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.beginPath();
        let started = false;
        line.values.forEach((value, index) => {
          if (value == null) {
            started = false;
            return;
          }
          if (!started) {
            ctx.moveTo(x(index), y(value));
            started = true;
          } else {
            ctx.lineTo(x(index), y(value));
          }
        });
        ctx.stroke();
        if (line.markers) {
          ctx.fillStyle = line.color;
          line.values.forEach((value, index) => {
            if (value == null) return;
            ctx.beginPath();
            ctx.arc(x(index), y(value), 3.2, 0, Math.PI * 2);
            ctx.fill();
          });
        }
      });

      const desiredTickCount = width < 620 ? 3 : range === "1d" ? 7 : range === "5d" ? 6 : 7;
      const tickCount = Math.min(desiredTickCount, points.length);
      ctx.fillStyle = "#718078";
      ctx.strokeStyle = "rgba(145, 167, 155, 0.08)";
      for (let tick = 0; tick < tickCount; tick += 1) {
        const index = Math.round((tick * (points.length - 1)) / (tickCount - 1));
        const xx = x(index);
        ctx.beginPath();
        ctx.moveTo(xx, padding.top);
        ctx.lineTo(xx, height - padding.bottom);
        ctx.stroke();
        ctx.textAlign = tick === 0 ? "left" : tick === tickCount - 1 ? "right" : "center";
        ctx.fillText(axisTimestamp(points[index].ts, range), xx, height - 10);
      }

      const hoverIndex = hoverIndexRef.current;
      if (hoverIndex != null) {
        const hoverValues = series.flatMap((line) => {
          const value = line.values[hoverIndex];
          return value == null ? [] : [{ ...line, value }];
        });
        if (hoverValues.length) {
          const xx = x(hoverIndex);
          const yy = y(hoverValues[0].value);
          ctx.strokeStyle = "rgba(214, 255, 95, .46)";
          ctx.lineWidth = 1;
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.moveTo(xx, padding.top);
          ctx.lineTo(xx, height - padding.bottom);
          ctx.stroke();
          ctx.setLineDash([]);

          hoverValues.forEach((line) => {
            ctx.fillStyle = line.color;
            ctx.beginPath();
            ctx.arc(xx, y(line.value), 4, 0, Math.PI * 2);
            ctx.fill();
          });

          const valueLabels = hoverValues.map((line) => `${line.label}  ${line.value >= 0 ? "+" : ""}${formatter(line.value)}`);
          const timeLabel = tooltipTimestamp(points[hoverIndex].ts);
          ctx.font = "12px var(--font-geist-mono), monospace";
          const tooltipWidth = Math.max(ctx.measureText(timeLabel).width, ...valueLabels.map((label) => ctx.measureText(label).width)) + 22;
          const tooltipHeight = 32 + valueLabels.length * 20;
          const tooltipX = xx + tooltipWidth + 14 < width - padding.right ? xx + 12 : xx - tooltipWidth - 12;
          const tooltipY = Math.max(padding.top + 8, Math.min(yy - tooltipHeight - 12, height - padding.bottom - tooltipHeight - 8));
          ctx.fillStyle = "rgba(8, 15, 11, .96)";
          ctx.strokeStyle = "rgba(214, 255, 95, .4)";
          ctx.lineWidth = 1;
          ctx.fillRect(tooltipX, tooltipY, tooltipWidth, tooltipHeight);
          ctx.strokeRect(tooltipX + .5, tooltipY + .5, tooltipWidth - 1, tooltipHeight - 1);
          ctx.textAlign = "left";
          valueLabels.forEach((label, index) => {
            ctx.fillStyle = hoverValues[index].color;
            ctx.fillText(label, tooltipX + 11, tooltipY + 20 + index * 20);
          });
          ctx.fillStyle = "#a3b0a8";
          ctx.fillText(timeLabel, tooltipX + 11, tooltipY + 20 + valueLabels.length * 20);
        }
      }
    };

    let animationFrame = 0;
    const scheduleDraw = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(draw);
    };

    scheduleDraw();
    const observer = new ResizeObserver(scheduleDraw);
    observer.observe(parent);
    const updateHover = (clientX: number) => {
      const bounds = canvas.getBoundingClientRect();
      const left = 68;
      const right = 18;
      const localX = clientX - bounds.left;
      const ratio = Math.max(0, Math.min(1, (localX - left) / Math.max(1, bounds.width - left - right)));
      hoverIndexRef.current = Math.round(ratio * (points.length - 1));
      scheduleDraw();
    };
    const handlePointerMove = (event: PointerEvent) => updateHover(event.clientX);
    const handlePointerLeave = () => {
      hoverIndexRef.current = null;
      scheduleDraw();
    };
    const handleFocus = () => {
      if (hoverIndexRef.current == null) hoverIndexRef.current = points.length - 1;
      scheduleDraw();
    };
    const handleBlur = () => {
      hoverIndexRef.current = null;
      scheduleDraw();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      const current = hoverIndexRef.current ?? points.length - 1;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        hoverIndexRef.current = Math.max(0, Math.min(points.length - 1, current + (event.key === "ArrowLeft" ? -1 : 1)));
        scheduleDraw();
      } else if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        hoverIndexRef.current = event.key === "Home" ? 0 : points.length - 1;
        scheduleDraw();
      }
    };
    canvas.addEventListener("pointermove", handlePointerMove);
    canvas.addEventListener("pointerleave", handlePointerLeave);
    canvas.addEventListener("focus", handleFocus);
    canvas.addEventListener("blur", handleBlur);
    canvas.addEventListener("keydown", handleKeyDown);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(animationFrame);
      canvas.removeEventListener("pointermove", handlePointerMove);
      canvas.removeEventListener("pointerleave", handlePointerLeave);
      canvas.removeEventListener("focus", handleFocus);
      canvas.removeEventListener("blur", handleBlur);
      canvas.removeEventListener("keydown", handleKeyDown);
    };
  }, [formatter, guides, points, range, series]);

  return <canvas ref={canvasRef} tabIndex={0} aria-label={`${ariaLabel} with ${points.length} points. Hover or use arrow keys for values.`} />;
}

function axisTimestamp(timestamp: number, range: string) {
  const date = new Date(timestamp);
  const options: Intl.DateTimeFormatOptions = range === "1d"
    ? { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: BEIJING_TIME_ZONE }
    : range === "5d"
      ? { month: "short", day: "2-digit", hour: "2-digit", hour12: false, timeZone: BEIJING_TIME_ZONE }
      : { month: "short", day: "2-digit", timeZone: BEIJING_TIME_ZONE };
  return new Intl.DateTimeFormat("en-US", options).format(date).replace(",", "");
}

function tooltipTimestamp(timestamp: number) {
  return `${new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: BEIJING_TIME_ZONE,
  }).format(new Date(timestamp)).replace(",", "")} UTC+8`;
}

function ContractCard({ leg, now }: { leg: Leg; now: number }) {
  return (
    <article className="contract-card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">{leg.key === "korean" ? "KOREAN ORDINARY" : "U.S. ADR · 10:1"}</p>
          <h3>{leg.inst_id.replace("-USDT-SWAP", "")}</h3>
        </div>
        <span className={`freshness ${leg.stale ? "stale" : ""}`}>{ageLabel(leg.ts, now)}</span>
      </div>
      <div className="mark-row">
        <span className="mark-value">{number(leg.mark)}</span>
        <span className="unit">USDT mark</span>
      </div>
      <div className="metric-grid">
        <div><span>INDEX</span><strong>{number(leg.index)}</strong></div>
        <div><span>MARK / INDEX</span><strong className={leg.basis_pct >= 0 ? "positive" : "negative"}>{signed(leg.basis_pct, 3)}%</strong></div>
        <div><span>CURRENT FUNDING</span><strong className={leg.funding.current >= 0 ? "positive" : "negative"}>{rate(leg.funding.current)}</strong></div>
        <div><span>LAST SETTLED</span><strong>{rate(leg.funding.settled)}</strong></div>
      </div>
      <div className="funding-clock">
        <span>CURRENT RATE COLLECTS IN</span>
        <strong>{countdown(leg.funding.funding_time, now)} · {beijingClock(leg.funding.funding_time)} UTC+8</strong>
      </div>
    </article>
  );
}

export default function Dashboard() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [selectedRange, setSelectedRange] = useState("5d");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(Date.now());

  const loadSnapshot = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/snapshot`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Data service returned ${response.status}`);
      setSnapshot(await response.json());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to reach data service");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async (range: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/history?range=${range}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`History service returned ${response.status}`);
      setHistory(await response.json());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load history");
    }
  }, []);

  useEffect(() => {
    loadSnapshot();
    const snapshotTimer = window.setInterval(loadSnapshot, 60_000);
    const clockTimer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => {
      window.clearInterval(snapshotTimer);
      window.clearInterval(clockTimer);
    };
  }, [loadSnapshot]);

  useEffect(() => {
    loadHistory(selectedRange);
    const historyTimer = window.setInterval(() => loadHistory(selectedRange), 300_000);
    return () => window.clearInterval(historyTimer);
  }, [loadHistory, selectedRange]);

  useEffect(() => {
    if (!history?.backfill.running) return;
    const timer = window.setInterval(() => loadHistory(selectedRange), 10_000);
    return () => window.clearInterval(timer);
  }, [history?.backfill.running, loadHistory, selectedRange]);

  const points = history?.points || [];
  const fundingPoints = history?.funding_points || [];
  const zscore = [...points].reverse().find((point) => point.zscore != null)?.zscore ?? null;
  const interpretation = !snapshot
    ? "Waiting for OKX"
    : snapshot.pair.premium_pct > 0.5
      ? "ADR RICH"
      : snapshot.pair.premium_pct < -0.5
        ? "ADR CHEAP"
        : "NEAR PARITY";
  const status = error ? "OFFLINE" : snapshot?.pair.korean.stale || snapshot?.pair.adr.stale ? "STALE" : "LIVE";

  const premiumSeries = useMemo(() => [
    { label: "ADR premium", values: points.map((point) => point.premium_pct), color: "#d6ff5f", width: 2.4 },
  ], [points]);
  const fundingSeries = useMemo(() => [
    { label: "SKHYNIX", values: fundingPoints.map((point) => point.korean_rate), color: "#76d9ff", width: 1.8, markers: true },
    { label: "SKHY", values: fundingPoints.map((point) => point.adr_rate), color: "#d6ff5f", width: 1.8, markers: true },
  ], [fundingPoints]);

  return (
    <main>
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark">H/B</span>
          <div>
            <p className="eyebrow">OKX RELATIVE VALUE</p>
            <h1>Hynix Basis</h1>
          </div>
        </div>
        <div className="header-actions">
          <div className={`status-pill ${status.toLowerCase()}`}><i />{status}</div>
          <span className="refresh-copy">60s refresh · mark price only</span>
          <button className="refresh-button" onClick={() => { loadSnapshot(); loadHistory(selectedRange); }} aria-label="Refresh market data">
            REFRESH
          </button>
        </div>
      </header>

      {error && (
        <div className="error-banner">
          <strong>DATA SERVICE DISCONNECTED</strong>
          <span>{error}. Start the Python API on port 8010; the dashboard will retry automatically.</span>
        </div>
      )}

      <section className="hero-grid">
        <article className="basis-hero">
          <div className="hero-topline">
            <div>
              <p className="eyebrow">ADR PREMIUM / DISCOUNT</p>
              <p className="formula">10 × SKHY MARK ÷ SKHYNIX MARK − 1</p>
            </div>
            <span className={`signal ${snapshot && snapshot.pair.premium_pct < 0 ? "cheap" : ""}`}>{interpretation}</span>
          </div>
          <div className="premium-value">
            {loading ? "—" : signed(snapshot?.pair.premium_pct)}<small>%</small>
          </div>
          <div className="hero-metrics">
            <div><span>ABSOLUTE SPREAD</span><strong>{snapshot ? `${signed(snapshot.pair.spread)} USDT` : "—"}</strong></div>
            <div><span>ADR EQUIVALENT</span><strong>{snapshot ? number(snapshot.pair.adr_equivalent) : "—"}</strong></div>
            <div><span>24H Z-SCORE</span><strong>{zscore == null ? "BUILDING" : signed(zscore)}</strong></div>
            <div><span>COMMON HISTORY</span><strong>{number(points.length, 0)} × 5M</strong></div>
          </div>
        </article>

        <article className="carry-card">
          <div>
            <p className="eyebrow">FUNDING CARRY · PER SETTLEMENT</p>
            <h2>Which leg pays?</h2>
          </div>
          <div className="carry-direction">
            <span>LONG KOREA</span><b>＋</b><span>SHORT ADR</span>
            <strong className={(snapshot?.pair.funding_carry.long_korean_short_adr ?? 0) >= 0 ? "positive" : "negative"}>
              {rate(snapshot?.pair.funding_carry.long_korean_short_adr)}
            </strong>
          </div>
          <div className="carry-direction">
            <span>SHORT KOREA</span><b>＋</b><span>LONG ADR</span>
            <strong className={(snapshot?.pair.funding_carry.short_korean_long_adr ?? 0) >= 0 ? "positive" : "negative"}>
              {rate(snapshot?.pair.funding_carry.short_korean_long_adr)}
            </strong>
          </div>
          <p className="fineprint">Positive value means estimated funding received. Equal normalized notional; fees excluded.</p>
        </article>
      </section>

      <section className="contracts-grid">
        {snapshot ? (
          <>
            <ContractCard leg={snapshot.pair.korean} now={now} />
            <ContractCard leg={snapshot.pair.adr} now={now} />
          </>
        ) : (
          <><div className="contract-card placeholder" /><div className="contract-card placeholder" /></>
        )}
      </section>

      <section className="chart-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">FIVE-MINUTE DIFFERENCE HISTORY · BEIJING TIME (UTC+8)</p>
            <h2>ADR premium / discount</h2>
          </div>
          <div className="range-control" aria-label="Chart range">
            {ranges.map(([value, label]) => (
              <button key={value} className={selectedRange === value ? "active" : ""} onClick={() => setSelectedRange(value)}>{label}</button>
            ))}
          </div>
        </div>
        <div className="chart-summary">
          <div className="legend"><span className="premium-line">(10 × SKHY ÷ SKHYNIX − 1) × 100</span></div>
          <strong className={(snapshot?.pair.premium_pct ?? 0) >= 0 ? "positive" : "negative"}>
            {snapshot ? `${signed(snapshot.pair.premium_pct)}%` : "—"}
          </strong>
        </div>
        <div className="chart-frame large premium-chart">
          {points.length > 1
            ? <CanvasChart points={points} series={premiumSeries} guides={premiumGuides} formatter={chartPercentageFormatter} range={selectedRange} ariaLabel="ADR premium percentage chart" />
            : <ChartEmpty backfill={history?.backfill} />}
        </div>
      </section>

      <section className="chart-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">SETTLED FUNDING HISTORY · BEIJING TIME (UTC+8)</p>
            <h2>Funding rates</h2>
          </div>
          <div className="range-control" aria-label="Funding chart range">
            {ranges.map(([value, label]) => (
              <button key={value} className={selectedRange === value ? "active" : ""} onClick={() => setSelectedRange(value)}>{label}</button>
            ))}
          </div>
        </div>
        <div className="chart-summary">
          <div className="legend">
            <span className="funding-korean-line">SKHYNIX settled</span>
            <span className="funding-adr-line">SKHY settled</span>
          </div>
          <strong>{number(fundingPoints.length, 0)} shared settlements · 3/day</strong>
        </div>
        <div className="chart-frame funding-chart">
          {fundingPoints.length > 1
            ? <CanvasChart points={fundingPoints} series={fundingSeries} guides={premiumGuides} formatter={chartFundingFormatter} range={selectedRange} ariaLabel="SKHYNIX and SKHY settled funding rate chart" />
            : <ChartEmpty backfill={history?.backfill} title="BUILDING FUNDING HISTORY" message="The Python collector is aligning settled OKX funding events." />}
        </div>
      </section>

      <section className="context-section">
        <div className="section-heading">
          <div><p className="eyebrow">MARKET CONTEXT</p><h2>Risk tape</h2></div>
          <span className="section-note">Korea: previous close · SPY/QQQ: trailing 24h</span>
        </div>
        <div className="context-grid">
          {(snapshot?.context || []).map((market) => (
            <article className="context-card" key={market.key}>
              <div className="context-top"><span>{market.label}</span><i className={market.stale ? "stale" : ""} /></div>
              <strong>{number(market.mark)}</strong>
              <p className={(market.change_pct ?? 0) >= 0 ? "positive" : "negative"}>{market.change_pct == null ? "—" : `${signed(market.change_pct)}%`}</p>
              <small>{market.proxy_note || market.inst_id}</small>
            </article>
          ))}
          {!snapshot && [1, 2, 3, 4].map((value) => <div className="context-card placeholder" key={value} />)}
        </div>
      </section>

      <footer>
        <div>
          <span>PAIR START</span><strong>{beijingDateTime(PAIR_START_MS)}</strong>
        </div>
        <div>
          <span>BACKFILL</span><strong>{history?.backfill.error ? "ERROR" : history?.backfill.running ? `RUNNING · ${number(history.backfill.rows_processed, 0)} ROWS` : history?.backfill.completed ? "COMPLETE" : "PENDING"}</strong>
        </div>
        <div>
          <span>LAST SNAPSHOT</span><strong>{snapshot ? beijingDateTime(snapshot.as_of) : "WAITING"}</strong>
        </div>
        <p>Research dashboard only. OKX perpetuals are leveraged derivatives; this interface does not place orders.</p>
      </footer>
    </main>
  );
}

function ChartEmpty({ backfill, title = "BUILDING COMMON HISTORY", message = "The Python collector is aligning five-minute OKX mark candles." }: { backfill?: Backfill; title?: string; message?: string }) {
  return (
    <div className="chart-empty">
      <span className="loader" />
      <strong>{backfill?.error ? "BACKFILL NEEDS ATTENTION" : title}</strong>
      <p>{backfill?.error || message}</p>
    </div>
  );
}
