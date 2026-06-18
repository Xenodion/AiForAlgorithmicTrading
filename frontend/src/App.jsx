import React, { useEffect, useMemo, useState } from 'react';
import createPlotlyComponent from 'react-plotly.js/factory';
import Plotly from 'plotly.js-dist-min';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Database,
  Info,
  Layers3,
  LineChart,
  Loader2,
  MessageCircle,
  Play,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Trash2,
  Wallet,
  Waves,
  X,
} from 'lucide-react';
import { apiGet, apiPost } from './api.js';

const Plot = createPlotlyComponent(Plotly);

const plotConfig = { displaylogo: false, responsive: true };
const plotLayout = {
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  font: { color: '#d8dedb', family: 'Inter, ui-sans-serif, system-ui' },
  margin: { l: 44, r: 18, t: 28, b: 42 },
  legend: { orientation: 'h', y: 1.12 },
  hoverlabel: { bgcolor: '#111818', bordercolor: '#2f4744' },
};

const tabs = [
  { id: 'data', label: 'Markets', icon: Database },
  { id: 'risk', label: 'Risk', icon: AlertTriangle },
  { id: 'orders', label: 'Orders', icon: Send },
  { id: 'surface', label: 'Surface', icon: Waves },
  { id: 'operations', label: 'Ops', icon: ShieldCheck },
];

const tabMeta = {
  data: {
    eyebrow: 'Market data',
    title: 'Markets & option chain',
    description: 'Spot, history, futures, forwards, option chain and surface preview.',
  },
  risk: {
    eyebrow: 'Risk lab',
    title: 'Pricing & scenarios',
    description: 'P&L breakdown, aggregated Greeks, spot-vol-time stress and local backtest.',
  },
  orders: {
    eyebrow: 'Execution safety',
    title: 'Tickets & dry-runs',
    description: 'Ticket preparation and validation with live routing disabled.',
  },
  surface: {
    eyebrow: 'Volatility model',
    title: 'Implied surface',
    description: '3D surface over strikes, smile per maturity and ATM term structure.',
  },
  operations: {
    eyebrow: 'Operations',
    title: 'Quality & delivery',
    description: 'Last run health, model versions, checks and artifacts.',
  },
};

const moduleHelp = {
  'Analytics run': {
    summary: 'Summary of the last full options + surface calculation saved locally.',
    bullets: [
      'Quickly shows whether the last option chain produced enough usable IV points.',
      'Rejections, warnings and calendar violations indicate the confidence level of the run.',
      'Starting point for diagnosing an empty, gappy or unstable surface.',
    ],
  },
  'Index price history': {
    summary: 'Underlying price history displayed as candlesticks with a moving average.',
    bullets: [
      'Puts implied volatility in context of the recent market regime.',
      'The underlying trend helps interpret smiles and risk scenarios.',
    ],
  },
  'Futures curve': {
    summary: 'Curve of listed futures on the index, by tenor and EUREX expiry.',
    bullets: [
      'Shows the market level available on futures.',
      'Helps compare spot, futures and implied forwards derived from options.',
    ],
  },
  'Forward curve': {
    summary: 'Implied forwards reconstructed via put-call parity when quote quality allows.',
    bullets: [
      'Primary source for working in log-moneyness rather than raw strike.',
      'Maturities without a usable pair fall back to spot/rate and should be monitored.',
    ],
  },
  'Options chain': {
    summary: 'Structured sample of the option chain by maturity, delta target, call/put ATM and quote quality.',
    bullets: [
      'Displays bid, ask, last, mid, IV, IV source, Greeks and quality status.',
      'QC columns indicate why a row is used or rejected for the surface.',
      'Delta granularity lets you read the smile without scanning the full raw chain.',
    ],
  },
  'Volatility surface preview': {
    summary: 'Quick preview of the implied surface built from eligible IV points.',
    bullets: [
      'Immediately reveals gaps, breaks or extrapolated zones.',
      'Yellow dots represent the observations used around the interpolated surface.',
    ],
  },
  'Euro Stoxx components': {
    summary: 'View of index constituents with the latest available prices.',
    bullets: [
      'Used to monitor breadth and the retrieval status of constituents.',
      'Useful to verify that the market data connection reaches beyond the main index.',
    ],
  },
  'Component deep dive': {
    summary: 'Detail of a selected constituent with spot snapshot and history.',
    bullets: [
      'Quickly inspect a specific stock in the universe.',
      'Helps isolate a missing or inconsistent constituent data point.',
    ],
  },
  'Black-Scholes pricer': {
    summary: 'Local call/put pricer with Greeks for testing a standardised option.',
    bullets: [
      'Simulates price, delta, gamma, vega and theta at controlled parameters.',
      'Serves as a pedagogical base and reference for the portfolio builder.',
    ],
  },
  'Scenario engine': {
    summary: 'Spot × volatility stress matrix to measure P&L sensitivity.',
    bullets: [
      'Shows how a position reacts to different market shocks.',
      'Highlights zones where gamma and vega dominate the result.',
    ],
  },
  'Portfolio builder': {
    summary: 'Build an option portfolio and aggregate Greeks in euros.',
    bullets: [
      'Add simulated positions from the pricer.',
      'Aggregates delta, gamma, vega and theta to read the overall exposure.',
    ],
  },
  'Saved strategies': {
    summary: 'Local library of risk strategies saved in parquet format.',
    bullets: [
      'Saves the current portfolio with its name, description and positions.',
      'Allows reloading a strategy after restarting the application.',
      'On load, positions are revalued using the current spot from the Risk tab.',
    ],
  },
  'Local P&L approximation': {
    summary: 'Local P&L approximation via delta, gamma, vega and theta.',
    bullets: [
      'Quick estimate for a move in spot, volatility and time.',
      'Useful to compare the Greeks approximation with a full repricing.',
    ],
  },
  'Portfolio backtest': {
    summary: 'Local backtest of simulated positions against historical spot and realised vol proxy.',
    bullets: [
      'Compares full P&L with a Greeks delta/gamma/vega/theta approximation.',
      'Vega uses a rolling realised volatility as a proxy, not a true historical IV surface.',
      'The decomposition helps explain where the gap between approximation and repricing comes from.',
    ],
  },
  'Account overview': {
    summary: 'Placeholder for account metrics, intentionally not routed live.',
    bullets: [
      'Live broker routing is disabled for safety.',
      'This block prepares the future account integration without exposing live orders.',
    ],
  },
  'Order ticket preview': {
    summary: 'Ticket preparation with validation and dry-run without broker submission.',
    bullets: [
      'Validates direction, quantity, order type and limit price.',
      'The dry-run creates a preview trace without sending a real order.',
    ],
  },
  'Open orders': {
    summary: 'Area reserved for open orders when routing is enabled.',
    bullets: [
      'Stays empty while the platform runs in safe mode.',
      'Will track live or paper order status once the integration is controlled.',
    ],
  },
  Positions: {
    summary: 'Area reserved for account positions retrieved from the broker.',
    bullets: [
      'Empty in the current mode as balances and positions are not connected.',
      'Will allow reconciliation of real positions against simulated risks.',
    ],
  },
  'Run health': {
    summary: 'Global health view of the last analytics run.',
    bullets: [
      'Condenses the pass/warn/fail status, freshness and model versions.',
      'First screen to check before trusting the surfaces.',
    ],
  },
  'Validation checks': {
    summary: 'List of quality controls certifying the last run.',
    bullets: [
      'Each card shows a threshold, a metric and a status.',
      'Warnings flag zones to watch without blocking the whole platform.',
    ],
  },
  Artifacts: {
    summary: 'Paths of JSON files generated to audit or replay the run.',
    bullets: [
      'Used to find persisted option rows, diagnostics and surfaces.',
      'Useful to compare two runs or investigate an anomaly.',
    ],
  },
  '3D volatility surface': {
    summary: 'Main implied surface displayed across delta, maturity and IV.',
    bullets: [
      'Shows the full volatility topology across delta buckets.',
      'Observed points help distinguish raw data from interpolation.',
    ],
  },
  'Volatility smile': {
    summary: 'Cross-section of the surface for a given maturity.',
    bullets: [
      'Read the smile/skew more precisely than in the 3D view.',
      'Useful to identify a local anomaly on one expiry.',
    ],
  },
  'ATM term structure': {
    summary: 'Term structure of IV around the ATM.',
    bullets: [
      'Reduces noise from illiquid strikes by focusing on the ATM or near-liquidity point.',
      'Helps compare maturities without being distorted by the full smile.',
    ],
  },
  'Surface statistics': {
    summary: 'Quality details and points used in surface construction.',
    bullets: [
      'Exposes accepted/rejected counts, IV sources, forwards, log-moneyness and total variance.',
      'The audit table for understanding a specific surface point.',
    ],
  },
};

function moduleHelpForTitle(title) {
  if (moduleHelp[title]) return moduleHelp[title];
  const dynamicMatch = Object.entries(moduleHelp).find(([key]) => title.startsWith(key));
  return dynamicMatch?.[1] ?? null;
}

const chatbotPrompts = {
  data: ['How to read the option chain?', 'Which maturity to choose?', 'Why look at forwards?'],
  risk: ['Build a conservative strategy', 'Explain delta gamma vega', 'Test a call spread'],
  orders: ['Prepare a ticket safely', 'Why is routing disabled?', 'Checklist before an order'],
  surface: ['Interpret the smile', 'Use the term structure', 'Spot a dangerous surface'],
  operations: ['Diagnose a warning', 'Validate a run', 'What to do with empty data?'],
};

const assistantIntro =
  "Hi, I can help you build your first risk strategies step by step. I stay educational: I don't send orders and I don't give investment recommendations.";

function assistantAnswer(input, activeTab) {
  const text = input.toLowerCase();
  const pageHint = {
    data: "On this page, start by checking the spot, liquid maturities, bid/ask quality and forwards before choosing a structure.",
    risk: "On this page, build a simple position, look at the Greeks, then stress spot and volatility before adding complexity.",
    orders: "On this page, the goal is to prepare and validate a ticket. Live routing stays disabled.",
    surface: "On this page, use the surface to understand where volatility is expensive or unstable by strike and maturity.",
    operations: "On this page, first check that the run is fresh, that the accepted points are sufficient and that warnings are understood.",
  }[activeTab];

  if (text.includes('delta') || text.includes('gamma') || text.includes('vega') || text.includes('theta') || text.includes('greek')) {
    return `${pageHint}\n\nGreeks turn an idea into a measurable exposure:\n- Delta: sensitivity to the underlying move.\n- Gamma: how fast delta changes; useful but can make P&L volatile.\n- Vega: sensitivity to implied volatility.\n- Theta: cost or gain as time passes.\n\nTo start, aim for a strategy whose P&L you can explain in 3 scenarios: market down, market flat, market up.`;
  }

  if (text.includes('call spread') || text.includes('put spread') || text.includes('spread')) {
    return `A vertical spread is often a good first structure because the risk is capped.\n\nBasic logic:\n1. Buy an option close to your scenario.\n2. Sell an option further out to reduce the cost.\n3. Accept a capped gain in exchange for a more readable risk.\n\nCheck in the app: net price, total delta, total vega, approximate max loss, then the spot × vol scenario in the Risk tab.`;
  }

  if (text.includes('straddle') || text.includes('strangle') || text.includes('volatil')) {
    return `A volatility strategy like straddle/strangle bets mainly on the magnitude of the move, not just direction.\n\nCheck before entering:\n- Is the ATM IV high or low vs other maturities?\n- Does the smile show a very expensive wing?\n- Is the theta acceptable if the market doesn't move?\n\nTo start, always compare buying volatility vs a capped spread: the first is purer, the second is often more controllable.`;
  }

  if (text.includes('hedge') || text.includes('protect') || text.includes('protection') || text.includes('cover')) {
    return `For a first hedge, think in terms of the risk you want to reduce.\n\nSimple method:\n1. Identify the main exposure: delta, vega or drawdown.\n2. Choose a protection that addresses it: put, put spread, collar or size reduction.\n3. Check the cost: premium paid, theta and opportunity loss.\n4. Stress test: spot down, vol up, time passing.\n\nA good hedge is understandable before it is sophisticated.`;
  }

  if (text.includes('surface') || text.includes('smile') || text.includes('term') || text.includes('iv')) {
    return `${pageHint}\n\nHow to use the surface:\n1. Look at the ATM term structure first for the general volatility level.\n2. Then check the smile to see if puts or calls are relatively expensive.\n3. Check the diagnostics: accepted points, rejections, common strikes, calendar violations.\n4. Avoid building a strategy on a sparse or last-only zone.\n\nA surface helps you choose where option pricing is exploitable, not predict direction alone.`;
  }

  if (text.includes('first') || text.includes('start') || text.includes('conserv') || text.includes('strategy') || text.includes('strateg')) {
    return `For a first risk strategy, I recommend a 5-step workflow:\n\n1. Hypothesis: directional, volatility, or hedge?\n2. Simple instrument: single option, vertical spread, or hedge.\n3. Bounded risk: define max loss, size and maturity.\n4. Greeks: delta for direction, vega for IV, theta for time cost.\n5. Scenarios: test down/flat/up and vol -/+ before any decision.\n\nA good first exercise in the app: create a call spread or put spread in Risk, then compare full P&L vs Greeks P&L.`;
  }

  if (text.includes('warning') || text.includes('error') || text.includes('empty') || text.includes('data')) {
    return `When a block looks suspicious, start from data quality:\n\n1. Ops tab: check the global status and warn/fail checks.\n2. Options chain: check QC Status, QC Reasons and Surface Eligible.\n3. Surface: check common strikes, rejected rows and calendar breaks.\n4. If many last-only or empty quotes: don't force a strategy on those points.\n\nA reliable strategy starts with usable data.`;
  }

  return `${pageHint}\n\nI can help you formulate a strategy if you give me three things: your market scenario, your time horizon, and the risk you want to limit. Example: "I want a conservative strategy if the index rises slightly over 1 month with capped loss".`;
}

function useResource(loader, deps, enabled = true) {
  const [state, setState] = useState({ data: null, loading: Boolean(enabled), error: null });
  const [refreshIndex, setRefreshIndex] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, loading: false, error: null });
      return undefined;
    }

    let alive = true;
    setState((current) => ({ ...current, loading: true, error: null }));

    loader()
      .then((data) => {
        if (alive) setState({ data, loading: false, error: null });
      })
      .catch((error) => {
        if (alive) setState({ data: null, loading: false, error });
      });

    return () => {
      alive = false;
    };
  }, [...deps, refreshIndex, enabled]);

  return {
    ...state,
    reload: () => setRefreshIndex((value) => value + 1),
  };
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatSigned(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const number = Number(value);
  return `${number >= 0 ? '+' : ''}${formatNumber(number, digits)}`;
}

function formatPercent(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return `${formatSigned(value, digits)}%`;
}

function formatEuro(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '€ —';
  return `€ ${formatSigned(value, digits)}`;
}

function movingAverage(rows, key, windowSize) {
  return rows.map((_, index) => {
    if (index + 1 < windowSize) return null;
    const slice = rows.slice(index + 1 - windowSize, index + 1);
    const values = slice.map((row) => Number(row[key])).filter((value) => Number.isFinite(value));
    if (!values.length) return null;
    return values.reduce((sum, value) => sum + value, 0) / values.length;
  });
}

function uniqueSorted(rows, key) {
  return [...new Set(rows.map((row) => row[key]).filter(Boolean))].sort();
}

function isSurfaceIvRow(row) {
  return Number.isFinite(Number(row['IV %']));
}

function buildSurface(rows) {
  const points = rows.filter(isSurfaceIvRow);
  const maturities = uniqueSorted(points, 'Maturity');
  const strikes = [...new Set(points.map((row) => Number(row.Strike)).filter(Number.isFinite))].sort(
    (a, b) => a - b,
  );

  const z = strikes.map((strike) =>
    maturities.map((maturity) => {
      const cellRows = points.filter((row) => Number(row.Strike) === strike && row.Maturity === maturity);
      if (!cellRows.length) return null;
      const ivValues = cellRows.map((row) => Number(row['IV %'])).filter(Number.isFinite);
      if (!ivValues.length) return null;
      return ivValues.reduce((sum, v) => sum + v, 0) / ivValues.length;
    }),
  );

  return { points, maturities, strikes, z };
}

function normalizeSurface(surfaceData, rows) {
  const grid = surfaceData?.grid;
  if (
    grid?.maturities?.length >= 2 &&
    grid?.strikes?.length >= 2 &&
    Array.isArray(grid?.z) &&
    grid.z.length >= 2
  ) {
    return {
      points: rows.filter(isSurfaceIvRow),
      maturities: grid.maturities,
      strikes: grid.strikes,
      z: grid.z,
    };
  }
  return buildSurface(rows);
}

function App() {
  const [activeTab, setActiveTab] = useState('data');
  const [notional, setNotional] = useState(10);
  const status = useResource(() => apiGet('/api/status'), [], true);
  const bootstrap = useResource(() => apiGet('/api/bootstrap'), [], status.data?.connected !== false);
  const options = useResource(() => apiGet('/api/options', { notional }), [notional], Boolean(bootstrap.data));
  const forwards = useResource(() => apiGet('/api/forwards', { notional }), [notional], Boolean(bootstrap.data));
  const surface = useResource(() => apiGet('/api/surface', { notional }), [notional], Boolean(bootstrap.data));
  const activeMeta = tabMeta[activeTab] ?? tabMeta.data;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Activity size={22} />
          </div>
          <div>
            <strong>Volatility</strong>
            <span>Infrastructure</span>
          </div>
        </div>

        <nav className="nav-list" aria-label="Main navigation">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
                type="button"
              >
                <Icon size={18} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>

        <StatusPanel status={status} bootstrap={bootstrap} />
      </aside>

      <main className="main">
        <header className="topbar workspace-header">
          <div>
            <p className="eyebrow">{activeMeta.eyebrow}</p>
            <h1>{activeMeta.title}</h1>
            <p className="page-subtitle">{activeMeta.description}</p>
          </div>
          <div className="topbar-actions">
            <span className="workspace-symbol">{bootstrap.data?.index?.symbol ?? 'SX5E'}</span>
            <StatusPill status={status} />
            <button className="icon-button" onClick={() => window.location.reload()} type="button" aria-label="Reload app">
              <RefreshCw size={17} />
            </button>
          </div>
        </header>

        {status.data?.connected === false ? (
          <ConnectionError error={status.data?.error} />
        ) : (
          <>
            {activeTab === 'data' && (
              <DataView
                bootstrap={bootstrap.data}
                notional={notional}
                setNotional={setNotional}
                options={options}
                forwards={forwards}
                surface={surface}
              />
            )}
            {activeTab === 'risk' && <RiskView bootstrap={bootstrap.data} />}
            {activeTab === 'orders' && <OrdersView bootstrap={bootstrap.data} />}
            {activeTab === 'surface' && <SurfaceView bootstrap={bootstrap.data} />}
            {activeTab === 'operations' && <OperationsView />}
          </>
        )}
      </main>
      <StrategyAssistant activeTab={activeTab} />
    </div>
  );
}

function StrategyAssistant({ activeTab }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: assistantIntro,
    },
  ]);
  const prompts = chatbotPrompts[activeTab] ?? chatbotPrompts.data;

  const sendMessage = (text) => {
    const clean = text.trim();
    if (!clean) return;
    setMessages((current) => [
      ...current,
      { role: 'user', content: clean },
      { role: 'assistant', content: assistantAnswer(clean, activeTab) },
    ]);
    setDraft('');
    setOpen(true);
  };

  return (
    <div className={`strategy-assistant ${open ? 'open' : ''}`}>
      {open && (
        <section className="assistant-panel" aria-label="Strategy assistant">
          <div className="assistant-header">
            <div>
              <span>Risk assistant</span>
              <strong>Guided strategies</strong>
            </div>
            <button className="icon-button" type="button" onClick={() => setOpen(false)} aria-label="Close strategy assistant">
              <X size={17} />
            </button>
          </div>

          <div className="assistant-messages">
            {messages.map((message, index) => (
              <div key={`${message.role}-${index}`} className={`assistant-message ${message.role}`}>
                {message.content}
              </div>
            ))}
          </div>

          <div className="assistant-prompts">
            {prompts.map((prompt) => (
              <button key={prompt} type="button" onClick={() => sendMessage(prompt)}>
                {prompt}
              </button>
            ))}
          </div>

          <form
            className="assistant-input"
            onSubmit={(event) => {
              event.preventDefault();
              sendMessage(draft);
            }}
          >
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Describe your idea or risk..."
            />
            <button className="primary-button" type="submit">
              <Send size={15} />
            </button>
          </form>
        </section>
      )}

      <button className="assistant-toggle" type="button" onClick={() => setOpen((value) => !value)} aria-label="Open strategy assistant">
        <MessageCircle size={21} />
      </button>
    </div>
  );
}

function StatusPanel({ status, bootstrap }) {
  const index = bootstrap.data?.index;
  return (
    <div className="sidebar-status">
      <div className="status-row">
        <span>Gateway</span>
        <StatusPill status={status} compact />
      </div>
      <div className="status-grid">
        <span>Conid</span>
        <strong>{index?.conid ?? '—'}</strong>
        <span>Option months</span>
        <strong>{index?.opt_months?.length ?? '—'}</strong>
        <span>Components</span>
        <strong>{bootstrap.data?.components?.length ?? '—'}</strong>
      </div>
    </div>
  );
}

function StatusPill({ status, compact = false }) {
  if (status.loading) {
    return (
      <span className="pill muted">
        <Loader2 size={14} className="spin" />
        {!compact && 'Connecting'}
      </span>
    );
  }
  if (status.data?.connected) {
    return (
      <span className="pill success">
        <CheckCircle2 size={14} />
        {!compact && 'IBKR connected'}
      </span>
    );
  }
  return (
    <span className="pill danger">
      <AlertTriangle size={14} />
      {!compact && 'Offline'}
    </span>
  );
}

function ConnectionError({ error }) {
  return (
    <section className="empty-state danger-state">
      <AlertTriangle size={28} />
      <h2>IBKR gateway unavailable</h2>
      <p>{error ?? 'Start Client Portal Gateway, log in, then refresh this page.'}</p>
    </section>
  );
}

function Panel({ title, icon: Icon, action, children, className = '' }) {
  const [helpOpen, setHelpOpen] = useState(false);
  const help = moduleHelpForTitle(String(title));

  return (
    <section className={`panel ${className}`}>
      <div className="panel-header">
        <div className="panel-title">
          {Icon && <Icon size={18} />}
          <h2>{title}</h2>
        </div>
        <div className="panel-actions">
          {help && (
            <button
              className="help-button"
              onClick={() => setHelpOpen(true)}
              type="button"
              aria-label={`Explain ${title}`}
              title="Explain this block"
            >
              <Info size={15} />
            </button>
          )}
          {action}
        </div>
      </div>
      {children}
      {helpOpen && help && (
        <div className="modal-backdrop" role="presentation" onClick={() => setHelpOpen(false)}>
          <div className="help-modal" role="dialog" aria-modal="true" aria-labelledby={`help-${String(title).replace(/\W+/g, '-')}`} onClick={(event) => event.stopPropagation()}>
            <div className="help-modal-header">
              <div>
                <span>Module</span>
                <h3 id={`help-${String(title).replace(/\W+/g, '-')}`}>{title}</h3>
              </div>
              <button className="icon-button" type="button" onClick={() => setHelpOpen(false)} aria-label="Close explanation">
                <X size={17} />
              </button>
            </div>
            <p>{help.summary}</p>
            <ul>
              {help.bullets.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}

function Insight({ children }) {
  return (
    <div className="insight">
      <Info size={16} />
      <p>{children}</p>
    </div>
  );
}

function MetricTile({ label, value, delta, tone = 'neutral' }) {
  return (
    <div className={`metric-tile ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {delta !== undefined && <em>{delta}</em>}
    </div>
  );
}

function LoadingBlock({ label = 'Loading data' }) {
  return (
    <div className="loading-block">
      <Loader2 size={18} className="spin" />
      <span>{label}</span>
    </div>
  );
}

function ErrorBlock({ error }) {
  return (
    <div className="error-block">
      <AlertTriangle size={17} />
      <span>{error?.message ?? 'Unable to load this section.'}</span>
    </div>
  );
}

function DataTable({ rows = [], columns, maxHeight = 420 }) {
  if (!rows?.length) {
    return <div className="table-empty">No rows available.</div>;
  }
  return (
    <div className="table-wrap" style={{ maxHeight }}>
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label ?? column.key}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${index}-${columns[0]?.key}`}>
              {columns.map((column) => {
                const raw = row[column.key];
                const value = column.format ? column.format(raw, row) : raw ?? '—';
                return (
                  <td key={column.key} className={column.className?.(raw, row) ?? ''}>
                    {value}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RefreshButton({ onClick, loading }) {
  return (
    <button className="secondary-button" onClick={onClick} type="button" disabled={loading}>
      <RefreshCw size={16} className={loading ? 'spin' : ''} />
      Refresh
    </button>
  );
}

function Segmented({ value, options, onChange }) {
  return (
    <div className="segmented">
      {options.map((option) => (
        <button
          key={option}
          className={value === option ? 'selected' : ''}
          type="button"
          onClick={() => onChange(option)}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function MarketHero({ bootstrap, spot, pointChange }) {
  const last = spot.data?.last;
  const close = spot.data?.close;
  const changePercent = spot.data?.chg_p;
  const tone = Number(pointChange) >= 0 ? 'good' : 'bad';

  return (
    <section className="market-hero">
      <div className="market-main">
        <span className="hero-label">{bootstrap?.index?.symbol ?? 'ESTX50'}</span>
        <strong>{formatNumber(last)}</strong>
        <em className={tone}>
          {formatSigned(pointChange)} pts · {formatPercent(changePercent)}
        </em>
      </div>
      <div className="market-stat-grid">
        <MetricTile label="High" value={formatNumber(spot.data?.high)} />
        <MetricTile label="Low" value={formatNumber(spot.data?.low)} />
        <MetricTile label="Close" value={formatNumber(close)} />
        <MetricTile label="Change" value={formatSigned(spot.data?.chg)} tone={tone} />
      </div>
      {spot.error && <ErrorBlock error={spot.error} />}
      {spot.loading && !spot.data && <LoadingBlock label="Loading spot" />}
    </section>
  );
}

function RunCompact({ latestRun }) {
  const manifest = latestRun.data?.manifest ?? {};
  const available = latestRun.data?.available;
  const calendarTone = manifest.calendar_violations ? 'bad' : 'good';
  const warningTone = manifest.warning_count ? 'warn' : 'good';

  return (
    <Panel title="Analytics run" icon={Database} className="compact-panel">
      {latestRun.error && <ErrorBlock error={latestRun.error} />}
      {latestRun.loading && !latestRun.data ? (
        <LoadingBlock label="Loading latest run" />
      ) : available ? (
        <>
          <div className="run-id-row">
            <span>{manifest.run_id?.slice(0, 17) ?? '—'}</span>
            <CheckBadge status={manifest.calendar_violations ? 'warn' : 'pass'} />
          </div>
          <div className="metric-grid two">
            <MetricTile label="Accepted IV" value={formatNumber(manifest.accepted_points, 0)} tone="good" />
            <MetricTile label="Rejected" value={formatNumber(manifest.rejected_rows, 0)} tone={manifest.rejected_rows ? 'warn' : 'good'} />
            <MetricTile label="Calendar" value={formatNumber(manifest.calendar_violations, 0)} tone={calendarTone} />
            <MetricTile label="Warnings" value={formatNumber(manifest.warning_count, 0)} tone={warningTone} />
          </div>
        </>
      ) : (
        <div className="table-empty">{latestRun.data?.message ?? 'No stored analytics run yet.'}</div>
      )}
    </Panel>
  );
}

function DataView({ bootstrap, notional, setNotional, options, forwards, surface }) {
  const [period, setPeriod] = useState('3y');
  const [bar, setBar] = useState('1w');
  const [selectedComponent, setSelectedComponent] = useState('');
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [optMaturity, setOptMaturity] = useState('All');
  const [optType, setOptType] = useState('All');
  const [optDeltaMin, setOptDeltaMin] = useState(-0.30);
  const [optDeltaMax, setOptDeltaMax] = useState(0.30);
  const components = bootstrap?.components ?? [];

  useEffect(() => {
    if (!selectedComponent && components.length) {
      setSelectedComponent(components[0].symbol);
    }
  }, [components, selectedComponent]);

  const spot = useResource(() => apiGet('/api/spot'), [refreshIndex], Boolean(bootstrap));
  const latestRun = useResource(() => apiGet('/api/runs/latest'), [refreshIndex], true);
  const history = useResource(() => apiGet('/api/history', { period, bar }), [period, bar, refreshIndex], Boolean(bootstrap));
  const futures = useResource(() => apiGet('/api/futures'), [refreshIndex], Boolean(bootstrap));
  const componentRows = useResource(() => apiGet('/api/components'), [refreshIndex], Boolean(bootstrap));
  const componentDetail = useResource(
    () => apiGet(`/api/component/${selectedComponent}`, { period, bar }),
    [selectedComponent, period, bar, refreshIndex],
    Boolean(selectedComponent),
  );

  const refreshAll = () => {
    setRefreshIndex((value) => value + 1);
    options.reload();
    forwards.reload();
    surface.reload();
  };
  const last = spot.data?.last;
  const close = spot.data?.close;
  const pointChange = last && close ? last - close : null;

  const allOptionRows = options.data ?? [];
  const optionMaturities = [...new Set(allOptionRows.map((r) => r.Maturity))].sort();
  const filteredOptionRows = allOptionRows.filter((row) => {
    if (optMaturity !== 'All' && row.Maturity !== optMaturity) return false;
    if (optType !== 'All' && row.Type !== optType) return false;
    const d = Number(row.Delta);
    if (Number.isFinite(d) && (d < optDeltaMin || d > optDeltaMax)) return false;
    return true;
  });

  return (
    <div className="view-stack">
      <div className="toolbar">
        <div className="control-row">
          <Field label="Period">
            <select value={period} onChange={(event) => setPeriod(event.target.value)}>
              {['6m', '1y', '2y', '3y'].map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Bar">
            <Segmented value={bar} options={['1w', '1d']} onChange={setBar} />
          </Field>
          <Field label="Multiplier">
            <input
              type="number"
              min="1"
              value={notional}
              onChange={(event) => setNotional(Number(event.target.value))}
            />
          </Field>
        </div>
        <RefreshButton onClick={refreshAll} loading={spot.loading || latestRun.loading || futures.loading || options.loading || forwards.loading || surface.loading} />
      </div>

      <div className="overview-grid">
        <MarketHero bootstrap={bootstrap} spot={spot} pointChange={pointChange} />
        <RunCompact latestRun={latestRun} />
      </div>

      <Panel title="Index price history" icon={LineChart}>
        <Insight>
          Candles show index points over time. The orange line is a 50-bar moving average for trend context.
        </Insight>
        {history.error && <ErrorBlock error={history.error} />}
        {history.loading && !history.data ? <LoadingBlock label="Loading history" /> : <HistoryChart rows={history.data ?? []} />}
      </Panel>

      <Panel title="Futures curve" icon={BarChart3}>
        <Insight>
          Tenors map to the nearest listed EUREX futures expiry, so multiple tenors can share the same contract month.
        </Insight>
        {futures.error && <ErrorBlock error={futures.error} />}
        {futures.loading && !futures.data ? (
          <LoadingBlock label="Loading futures" />
        ) : (
          <>
            <FuturesChart rows={futures.data ?? []} />
            <DataTable
              rows={futures.data ?? []}
              columns={[
                { key: 'Tenor' },
                { key: 'Expiry' },
                { key: 'Last', format: (value) => formatNumber(value) },
                { key: 'Bid', format: (value) => formatNumber(value) },
                { key: 'Ask', format: (value) => formatNumber(value) },
              ]}
              maxHeight={280}
            />
          </>
        )}
      </Panel>

      <Panel title="Forward curve" icon={LineChart}>
        <Insight>
          Forwards are inferred from call-put parity when a usable pair exists, otherwise the maturity is marked with a spot/rate fallback.
        </Insight>
        {forwards.error && <ErrorBlock error={forwards.error} />}
        {forwards.loading && !forwards.data ? (
          <LoadingBlock label="Building forwards" />
        ) : (
          <DataTable
            rows={forwards.data?.rows ?? []}
            columns={[
              { key: 'Maturity', format: (value) => fmtMaturity(value) },
              { key: 'Forward', format: (value) => formatNumber(value) },
              { key: 'Source' },
              { key: 'Candidate Count', format: (value) => formatNumber(value, 0) },
              { key: 'Max Abs Residual', format: (value) => formatNumber(value, 4) },
            ]}
            maxHeight={280}
          />
        )}
      </Panel>

      <Panel title="Options chain" icon={Layers3}>
        <Insight>
          All listed strikes within ±10% of spot across 6 maturities — OTM puts below ATM, OTM calls above, both Put and Call at the ATM strike. Delta default is clamped to [−0.30, +0.30].
        </Insight>
        {options.error && <ErrorBlock error={options.error} />}
        {options.loading && !options.data ? (
          <LoadingBlock label="Loading options" />
        ) : (
          <>
            <div className="control-row">
              <Field label="Maturity">
                <select value={optMaturity} onChange={(e) => setOptMaturity(e.target.value)}>
                  <option value="All">All</option>
                  {optionMaturities.map((m) => (
                    <option key={m} value={m}>
                      {m.slice(0, 4)}-{m.slice(4, 6)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Type">
                <Segmented value={optType} options={['All', 'Put', 'Call']} onChange={setOptType} />
              </Field>
              <Field label="Δ min">
                <input
                  type="number"
                  step="0.01"
                  min="-1"
                  max="1"
                  value={optDeltaMin}
                  onChange={(e) => setOptDeltaMin(Number(e.target.value))}
                />
              </Field>
              <Field label="Δ max">
                <input
                  type="number"
                  step="0.01"
                  min="-1"
                  max="1"
                  value={optDeltaMax}
                  onChange={(e) => setOptDeltaMax(Number(e.target.value))}
                />
              </Field>
              <Field label=" ">
                <span style={{ fontSize: 12, color: '#7fa99c', alignSelf: 'center' }}>
                  {filteredOptionRows.length} / {allOptionRows.length} rows
                </span>
              </Field>
            </div>
            <DataTable rows={filteredOptionRows} columns={optionColumns} maxHeight={540} />
          </>
        )}
      </Panel>

      <Panel title="Volatility surface preview" icon={Waves}>
        {surface.error && <ErrorBlock error={surface.error} />}
        {surface.loading && !surface.data ? (
          <LoadingBlock label="Loading surface" />
        ) : (
          <SurfaceChart surfaceData={surface.data} rows={options.data ?? []} height={460} />
        )}
      </Panel>

      <Panel title={`Euro Stoxx components ${components.length ? `(${components.length})` : ''}`} icon={Database}>
        {componentRows.error && <ErrorBlock error={componentRows.error} />}
        {componentRows.loading && !componentRows.data ? (
          <LoadingBlock label="Loading components" />
        ) : (
          <DataTable
            rows={componentRows.data ?? []}
            columns={[
              { key: 'Symbol' },
              { key: 'Name' },
              { key: 'Last', format: (value) => formatNumber(value) },
              { key: 'Bid', format: (value) => formatNumber(value) },
              { key: 'Ask', format: (value) => formatNumber(value) },
            ]}
          />
        )}
      </Panel>

      <Panel title="Component deep dive" icon={LineChart}>
        <div className="control-row">
          <Field label="Stock">
            <select value={selectedComponent} onChange={(event) => setSelectedComponent(event.target.value)}>
              {components.map((component) => (
                <option key={component.symbol} value={component.symbol}>
                  {component.name} ({component.symbol})
                </option>
              ))}
            </select>
          </Field>
        </div>
        {componentDetail.error && <ErrorBlock error={componentDetail.error} />}
        {componentDetail.loading && !componentDetail.data ? (
          <LoadingBlock label="Loading component" />
        ) : (
          <>
            <div className="metric-grid six">
              <MetricTile label="Last" value={formatNumber(componentDetail.data?.spot?.last)} />
              <MetricTile label="High" value={formatNumber(componentDetail.data?.spot?.high)} />
              <MetricTile label="Low" value={formatNumber(componentDetail.data?.spot?.low)} />
              <MetricTile label="Close" value={formatNumber(componentDetail.data?.spot?.close)} />
              <MetricTile label="Change" value={formatSigned(componentDetail.data?.spot?.chg)} />
              <MetricTile label="Change %" value={formatPercent(componentDetail.data?.spot?.chg_p)} />
            </div>
            <HistoryChart rows={componentDetail.data?.history ?? []} title={componentDetail.data?.name} />
          </>
        )}
      </Panel>
    </div>
  );
}

const optionColumns = [
  {
    key: 'Maturity',
    format: (value) => (value ? String(value).slice(0, 4) + '-' + String(value).slice(4, 6) : '—'),
  },
  { key: 'Type' },
  { key: 'Strike', format: (value) => formatNumber(value, 0) },
  { key: 'Delta', format: (value) => formatNumber(value, 4) },
  { key: 'Delta (€)', format: (value) => formatNumber(value, 4) },
  { key: 'Bid', format: (value) => formatNumber(value) },
  { key: 'Ask', format: (value) => formatNumber(value) },
  { key: 'Last', format: (value) => formatNumber(value) },
  { key: 'Mid', format: (value) => formatNumber(value) },
  { key: 'Spread', format: (value) => formatNumber(value) },
  { key: 'Gamma', format: (value) => formatNumber(value, 6) },
  { key: 'Gamma (€)', format: (value) => formatNumber(value, 4) },
  { key: 'Vega', format: (value) => formatNumber(value, 4) },
  { key: 'Vega (€)', format: (value) => formatNumber(value, 4) },
  { key: 'Root Time Vega', format: (value) => formatNumber(value, 4) },
  { key: 'Root Time Vega (€)', label: 'Root TV (€)', format: (value) => formatNumber(value, 4) },
  { key: 'Theta', format: (value) => formatNumber(value, 4) },
  { key: 'Theta (€)', format: (value) => formatNumber(value, 4) },
  {
    key: 'IV %',
    label: 'IV',
    format: (value) => (value === null || value === undefined ? '—' : `${formatNumber(value, 2)}%`),
  },
  {
    key: 'IV Source',
    format: (value) => <span className={`source-pill ${value === 'IBKR' ? 'live' : 'calc'}`}>{value ?? '—'}</span>,
  },
  { key: 'IV Status' },
  { key: 'IV Price', format: (value) => formatNumber(value) },
  { key: 'IV Residual', format: (value) => formatNumber(value, 6) },
];

function HistoryChart({ rows, title = '' }) {
  if (!rows.length) return <div className="table-empty">Historical data unavailable.</div>;
  const ma50 = movingAverage(rows, 'close', 50);
  return (
    <Plot
      data={[
        {
          type: 'candlestick',
          x: rows.map((row) => row.date),
          open: rows.map((row) => row.open),
          high: rows.map((row) => row.high),
          low: rows.map((row) => row.low),
          close: rows.map((row) => row.close),
          name: title || 'Price',
          increasing: { line: { color: '#37b77a' } },
          decreasing: { line: { color: '#e45f5f' } },
        },
        {
          type: 'scatter',
          mode: 'lines',
          x: rows.map((row) => row.date),
          y: ma50,
          name: '50-bar MA',
          line: { color: '#d9a441', width: 1.6, dash: 'dot' },
        },
      ]}
      layout={{
        ...plotLayout,
        height: 420,
        xaxis: { rangeslider: { visible: false } },
        yaxis: { title: 'Index points' },
      }}
      config={plotConfig}
      useResizeHandler
      className="plot"
    />
  );
}

function FuturesChart({ rows }) {
  if (!rows.length) return <div className="table-empty">Futures data unavailable.</div>;
  return (
    <Plot
      data={[
        {
          type: 'scatter',
          mode: 'lines+markers',
          x: rows.map((row) => row.Tenor),
          y: rows.map((row) => row.Bid),
          name: 'Bid',
          line: { color: '#48ad73', width: 2 },
          connectgaps: false,
        },
        {
          type: 'scatter',
          mode: 'lines+markers',
          x: rows.map((row) => row.Tenor),
          y: rows.map((row) => row.Last),
          name: 'Last',
          line: { color: '#4b9bd8', width: 2 },
          connectgaps: false,
        },
        {
          type: 'scatter',
          mode: 'lines+markers',
          x: rows.map((row) => row.Tenor),
          y: rows.map((row) => row.Ask),
          name: 'Ask',
          line: { color: '#dc6b59', width: 2 },
          connectgaps: false,
        },
      ]}
      layout={{
        ...plotLayout,
        height: 360,
        xaxis: { title: 'Tenor' },
        yaxis: { title: 'Index points' },
      }}
      config={plotConfig}
      useResizeHandler
      className="plot"
    />
  );
}

function fmtMaturity(m) {
  const s = String(m);
  return s.length === 6 ? `${s.slice(0, 4)}-${s.slice(4, 6)}` : s;
}

function SurfaceChart({ rows = [], surfaceData = null, height = 560 }) {
  const surface = useMemo(() => normalizeSurface(surfaceData, rows), [surfaceData, rows]);
  if (!surface.points.length) {
    return <div className="table-empty">Surface requires rows with IV % data.</div>;
  }

  const enoughGrid = surface.maturities.length >= 2 && surface.strikes.length >= 2;
  const data = enoughGrid
    ? [
        {
          type: 'surface',
          x: surface.maturities.map(fmtMaturity),
          y: surface.strikes,
          z: surface.z,
          colorscale: 'RdYlGn',
          reversescale: false,
          colorbar: { title: 'IV %', thickness: 14 },
          hovertemplate: 'Maturity=%{x}<br>Strike=%{y}<br>IV=%{z:.2f}%<extra></extra>',
          name: 'IV surface',
        },
        {
          type: 'scatter3d',
          mode: 'markers',
          x: surface.points.map((row) => fmtMaturity(row.Maturity)),
          y: surface.points.map((row) => Number(row.Strike)),
          z: surface.points.map((row) => Number(row['IV %'])),
          marker: { size: 3, color: '#f5d76e', opacity: 0.85 },
          hovertemplate: 'Observed<br>Maturity=%{x}<br>Strike=%{y}<br>IV=%{z:.2f}%<extra></extra>',
          name: 'Observed quotes',
        },
      ]
    : [
        {
          type: 'scatter3d',
          mode: 'markers',
          x: surface.points.map((row) => fmtMaturity(row.Maturity)),
          y: surface.points.map((row) => Number(row.Strike)),
          z: surface.points.map((row) => Number(row['IV %'])),
          marker: {
            size: 5,
            color: surface.points.map((row) => Number(row['IV %'])),
            colorscale: 'RdYlGn',
            colorbar: { title: 'IV %', thickness: 14 },
          },
          hovertemplate: 'Maturity=%{x}<br>Strike=%{y}<br>IV=%{z:.2f}%<extra></extra>',
        },
      ];

  return (
    <Plot
      data={data}
      layout={{
        ...plotLayout,
        height,
        scene: {
          xaxis: { title: 'Maturity', gridcolor: '#263937' },
          yaxis: { title: 'Strike', gridcolor: '#263937' },
          zaxis: { title: 'IV (%)', gridcolor: '#263937' },
          camera: { eye: { x: 1.55, y: 1.55, z: 0.95 } },
        },
      }}
      config={plotConfig}
      useResizeHandler
      className="plot"
    />
  );
}

function RiskView({ bootstrap }) {
  const liveSpot = useResource(() => apiGet('/api/spot'), [], Boolean(bootstrap));
  const [selectedType, setSelectedType] = useState('call');
  const [form, setForm] = useState({
    spot: 5000,
    strike: 5000,
    maturity: 0.25,
    ratePercent: 3,
    sigmaPercent: 20,
    multiplier: 10,
    quantity: 1,
    label: 'ESTX50 ATM C',
  });
  const [portfolio, setPortfolio] = useState([]);
  const [pnlInputs, setPnlInputs] = useState({ dS: 0, volMovePct: 0, days: 1 });
  const [backtestPeriod, setBacktestPeriod] = useState('3m');
  const [backtest, setBacktest] = useState({ data: null, loading: false, error: null });
  const savedStrategies = useResource(() => apiGet('/api/risk/strategies'), [], true);
  const [activeStrategyId, setActiveStrategyId] = useState(null);
  const [strategyName, setStrategyName] = useState('My strategy');
  const [strategyDescription, setStrategyDescription] = useState('');
  const [strategyAction, setStrategyAction] = useState({ loading: false, error: null, message: null });

  useEffect(() => {
    const spotValue = liveSpot.data?.last ?? liveSpot.data?.close;
    if (spotValue) {
      setForm((current) => ({
        ...current,
        spot: Math.round(spotValue),
        strike: Math.round(spotValue / 100) * 100,
      }));
    }
  }, [liveSpot.data?.last, liveSpot.data?.close]);

  const pricingParams = {
    spot_value: form.spot,
    strike: form.strike,
    maturity: form.maturity,
    rate: form.ratePercent / 100,
    sigma: form.sigmaPercent / 100,
    multiplier: form.multiplier,
  };
  const pricing = useResource(() => apiGet('/api/risk/pricer', pricingParams), Object.values(pricingParams), true);
  const scenario = useResource(
    () => apiGet('/api/risk/scenario', { ...pricingParams, option_type: selectedType }),
    [...Object.values(pricingParams), selectedType],
    true,
  );

  const updateForm = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const addPosition = async () => {
    const qty = Number(form.quantity);
    if (!Number.isFinite(qty) || qty === 0) {
      setStrategyAction({ loading: false, error: null, message: 'Qty cannot be zero. Use a positive integer for long positions, negative for short.' });
      return;
    }
    const payload = {
      label: form.label || `${bootstrap?.index?.symbol ?? 'Index'} ${selectedType.toUpperCase()}`,
      option_type: selectedType,
      strike: Number(form.strike),
      maturity: Number(form.maturity),
      rate: Number(form.ratePercent) / 100,
      sigma: Number(form.sigmaPercent) / 100,
      quantity: qty,
      multiplier: Number(form.multiplier),
    };
    const response = await apiPost('/api/risk/position', payload, { spot_value: Number(form.spot) });
    setPortfolio((current) => [...current, { ...response, input: payload, id: crypto.randomUUID() }]);
  };

  const valueSavedPositions = async (positions) => {
    const spotValue = Number(form.spot);
    return Promise.all(
      positions.map(async (position) => {
        const response = await apiPost('/api/risk/position', position, { spot_value: spotValue });
        return { ...response, input: position, id: crypto.randomUUID() };
      }),
    );
  };

  const saveCurrentStrategy = async () => {
    if (!portfolio.length) {
      setStrategyAction({ loading: false, error: null, message: 'Add at least one position before saving.' });
      return;
    }
    if (!strategyName.trim()) {
      setStrategyAction({ loading: false, error: null, message: 'Give the strategy a name.' });
      return;
    }

    setStrategyAction({ loading: true, error: null, message: null });
    try {
      const saved = await apiPost('/api/risk/strategies', {
        strategy_id: activeStrategyId,
        name: strategyName.trim(),
        description: strategyDescription.trim(),
        underlying: bootstrap?.index?.symbol ?? 'ESTX50',
        positions: portfolio.map((item) => item.input),
      });
      setActiveStrategyId(saved.strategy_id);
      setStrategyName(saved.name ?? strategyName);
      setStrategyDescription(saved.description ?? strategyDescription);
      savedStrategies.reload();
      setStrategyAction({ loading: false, error: null, message: 'Strategy saved.' });
    } catch (error) {
      setStrategyAction({ loading: false, error, message: null });
    }
  };

  const loadSavedStrategy = async (strategyId) => {
    setStrategyAction({ loading: true, error: null, message: null });
    try {
      const strategy = await apiGet(`/api/risk/strategies/${strategyId}`);
      const valued = await valueSavedPositions(strategy.positions ?? []);
      setPortfolio(valued);
      setActiveStrategyId(strategy.strategy_id);
      setStrategyName(strategy.name ?? 'My strategy');
      setStrategyDescription(strategy.description ?? '');
      setStrategyAction({ loading: false, error: null, message: 'Strategy loaded.' });
      runBacktest(strategy.positions ?? []);
    } catch (error) {
      setStrategyAction({ loading: false, error, message: null });
    }
  };

  const deleteSavedStrategy = async (strategyId) => {
    setStrategyAction({ loading: true, error: null, message: null });
    try {
      await apiPost('/api/risk/strategies/delete', { strategy_id: strategyId });
      if (activeStrategyId === strategyId) {
        setActiveStrategyId(null);
      }
      savedStrategies.reload();
      setStrategyAction({ loading: false, error: null, message: 'Strategy deleted.' });
    } catch (error) {
      setStrategyAction({ loading: false, error, message: null });
    }
  };

  const startNewStrategy = () => {
    setPortfolio([]);
    setActiveStrategyId(null);
    setStrategyName('My strategy');
    setStrategyDescription('');
    setBacktest({ data: null, loading: false, error: null });
    setStrategyAction({ loading: false, error: null, message: 'Simulation cleared.' });
  };

  const aggregate = portfolio.reduce(
    (acc, item) => ({
      delta: acc.delta + (item.euroGreeks?.delta ?? 0),
      gamma: acc.gamma + (item.euroGreeks?.gamma ?? 0),
      vega: acc.vega + (item.euroGreeks?.vega ?? 0),
      theta: acc.theta + (item.euroGreeks?.theta ?? 0),
    }),
    { delta: 0, gamma: 0, vega: 0, theta: 0 },
  );

  const localPnl = portfolio.reduce((sum, item) => {
    const g = item.greeks ?? {};
    const raw =
      (g.delta ?? 0) * pnlInputs.dS +
      0.5 * (g.gamma ?? 0) * pnlInputs.dS ** 2 +
      (g.vega ?? 0) * pnlInputs.volMovePct +
      (g.theta ?? 0) * pnlInputs.days;
    return sum + raw * (item.input?.quantity ?? 1) * (item.input?.multiplier ?? 1);
  }, 0);

  const runBacktest = async (positionsInput) => {
    const positions = positionsInput ?? portfolio.map((item) => item.input);
    if (!positions.length) return;
    setBacktest({ data: null, loading: true, error: null });
    try {
      const data = await apiPost('/api/risk/backtest/report', {
        period: backtestPeriod,
        positions,
      });
      setBacktest({ data, loading: false, error: null });
    } catch (error) {
      setBacktest({ data: null, loading: false, error });
    }
  };

  return (
    <div className="view-stack">
      <Panel title="Black-Scholes pricer" icon={Activity}>
        <div className="form-grid">
          <Field label="Spot">
            <input type="number" value={form.spot} onChange={(event) => updateForm('spot', Number(event.target.value))} />
          </Field>
          <Field label="Strike">
            <input type="number" value={form.strike} onChange={(event) => updateForm('strike', Number(event.target.value))} />
          </Field>
          <Field label="Maturity (yr)">
            <input type="number" step="0.01" value={form.maturity} onChange={(event) => updateForm('maturity', Number(event.target.value))} />
          </Field>
          <Field label="Rate (%)">
            <input type="number" step="0.25" value={form.ratePercent} onChange={(event) => updateForm('ratePercent', Number(event.target.value))} />
          </Field>
          <Field label="Vol (%)">
            <input type="number" step="1" value={form.sigmaPercent} onChange={(event) => updateForm('sigmaPercent', Number(event.target.value))} />
          </Field>
          <Field label="Multiplier">
            <input type="number" value={form.multiplier} onChange={(event) => updateForm('multiplier', Number(event.target.value))} />
          </Field>
        </div>

        {pricing.loading && !pricing.data ? (
          <LoadingBlock label="Pricing" />
        ) : (
          <div className="split-grid">
            {['call', 'put'].map((optionType) => (
              <PricingCard
                key={optionType}
                optionType={optionType}
                data={pricing.data?.[optionType]}
                selected={selectedType === optionType}
                onSelect={() => setSelectedType(optionType)}
              />
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Scenario engine" icon={BarChart3}>
        <div className="panel-inline">
          <Segmented value={selectedType} options={['call', 'put']} onChange={setSelectedType} />
        </div>
        {scenario.error && <ErrorBlock error={scenario.error} />}
        {scenario.loading && !scenario.data ? <LoadingBlock label="Running scenarios" /> : <ScenarioMatrix rows={scenario.data ?? []} />}
      </Panel>

      <Panel title="Portfolio builder" icon={Wallet}>
        <div className="form-grid strategy-form">
          <Field label="Strategy name">
            <input value={strategyName} onChange={(event) => setStrategyName(event.target.value)} />
          </Field>
          <Field label="Description">
            <textarea value={strategyDescription} onChange={(event) => setStrategyDescription(event.target.value)} rows={2} />
          </Field>
          <button className="secondary-button danger-button form-action" type="button" onClick={startNewStrategy}>
            <Trash2 size={16} />
            Clear
          </button>
          <button className="primary-button form-action" type="button" onClick={saveCurrentStrategy} disabled={strategyAction.loading || !portfolio.length}>
            <Database size={16} />
            Save
          </button>
        </div>
        {strategyAction.error && <ErrorBlock error={strategyAction.error} />}
        {strategyAction.message && <Insight>{strategyAction.message}</Insight>}

        <div className="form-grid portfolio-form">
          <Field label="Label">
            <input value={form.label} onChange={(event) => updateForm('label', event.target.value)} />
          </Field>
          <Field label="Type">
            <Segmented value={selectedType} options={['call', 'put']} onChange={setSelectedType} />
          </Field>
          <Field label="Strike K">
            <input type="number" min="1" value={form.strike} onChange={(event) => updateForm('strike', Number(event.target.value))} />
          </Field>
          <Field label="T (yr)">
            <input type="number" step="0.01" min="0.01" value={form.maturity} onChange={(event) => updateForm('maturity', Number(event.target.value))} />
          </Field>
          <Field label="σ (%)">
            <input type="number" step="1" min="1" value={form.sigmaPercent} onChange={(event) => updateForm('sigmaPercent', Number(event.target.value))} />
          </Field>
          <Field label="Qty (− = short)">
            <input type="number" step="1" value={form.quantity} onChange={(event) => updateForm('quantity', Number(event.target.value))} />
          </Field>
          <button className="primary-button form-action" type="button" onClick={addPosition}>
            <Plus size={16} />
            Add position
          </button>
        </div>

        {portfolio.length ? (
          <>
            <div className="metric-grid four">
              <MetricTile label="Total Delta" value={formatEuro(aggregate.delta)} tone={aggregate.delta >= 0 ? 'good' : 'bad'} />
              <MetricTile label="Total Gamma" value={formatEuro(aggregate.gamma)} />
              <MetricTile label="Total Vega" value={formatEuro(aggregate.vega)} />
              <MetricTile label="Total Theta" value={formatEuro(aggregate.theta)} tone={aggregate.theta >= 0 ? 'good' : 'bad'} />
            </div>
            <DataTable
              rows={portfolio}
              columns={[
                { key: 'label' },
                { key: 'optionType', label: 'Type' },
                { key: 'strike', format: (value) => formatNumber(value, 0) },
                { key: 'maturity', format: (value) => formatNumber(value, 2) },
                { key: 'price', format: (value) => formatNumber(value, 4) },
                { key: 'quantity', label: 'Qty', format: (value) => (Number.isFinite(value) ? (value > 0 ? `+${value}` : String(value)) : '—') },
                { key: 'euroGreeks', label: '€ Delta', format: (value) => formatEuro(value?.delta) },
                { key: 'euroGreeks', label: '€ Vega', format: (value) => formatEuro(value?.vega) },
              ]}
              maxHeight={280}
            />
          </>
        ) : (
          <div className="table-empty">Add positions to start aggregating Greeks.</div>
        )}
      </Panel>

      <Panel title="Local P&L approximation" icon={LineChart}>
        {portfolio.length === 0 ? (
          <div className="table-empty">Build a portfolio above, then move the sliders to estimate P&amp;L.</div>
        ) : (
          <>
            <Insight>
              Simulating <strong>{strategyName}</strong> · {portfolio.length} position{portfolio.length !== 1 ? 's' : ''}
            </Insight>
            <div className="slider-grid">
              <Field label={`Spot move: ${pnlInputs.dS} pts`}>
                <input type="range" min="-500" max="500" step="10" value={pnlInputs.dS} onChange={(event) => setPnlInputs((v) => ({ ...v, dS: Number(event.target.value) }))} />
              </Field>
              <Field label={`Vol move: ${pnlInputs.volMovePct} vol pts`}>
                <input type="range" min="-10" max="10" step="1" value={pnlInputs.volMovePct} onChange={(event) => setPnlInputs((v) => ({ ...v, volMovePct: Number(event.target.value) }))} />
              </Field>
              <Field label={`Time: ${pnlInputs.days} days`}>
                <input type="range" min="0" max="30" step="1" value={pnlInputs.days} onChange={(event) => setPnlInputs((v) => ({ ...v, days: Number(event.target.value) }))} />
              </Field>
            </div>
            <div className="metric-grid one">
              <MetricTile label="Estimated P&L" value={formatEuro(localPnl)} tone={localPnl >= 0 ? 'good' : 'bad'} />
            </div>
          </>
        )}
      </Panel>

      <Panel
        title="Portfolio backtest"
        icon={LineChart}
        action={
          <button className="secondary-button" type="button" disabled={!portfolio.length || backtest.loading} onClick={() => runBacktest()}>
            <Play size={16} />
            Re-run
          </button>
        }
      >
        {portfolio.length === 0 ? (
          <div className="table-empty">Load or build a portfolio above — the backtest runs automatically on load.</div>
        ) : (
          <>
            <Insight>
              Backtesting <strong>{strategyName}</strong> · {portfolio.length} position{portfolio.length !== 1 ? 's' : ''}
            </Insight>
            <div className="control-row">
              <Field label="Lookback">
                <select value={backtestPeriod} onChange={(event) => setBacktestPeriod(event.target.value)}>
                  {['1m', '3m', '6m', '1y'].map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </Field>
            </div>
            {backtest.error && <ErrorBlock error={backtest.error} />}
            {backtest.loading ? <LoadingBlock label="Running backtest" /> : <BacktestChart data={backtest.data} />}
          </>
        )}
      </Panel>

      <Panel
        title="Saved strategies"
        icon={Database}
        action={<RefreshButton onClick={savedStrategies.reload} loading={savedStrategies.loading} />}
      >
        {savedStrategies.error && <ErrorBlock error={savedStrategies.error} />}
        {savedStrategies.loading && !savedStrategies.data ? (
          <LoadingBlock label="Loading strategies" />
        ) : !(savedStrategies.data?.strategies?.length) ? (
          <div className="table-empty">No saved strategies yet — build a portfolio and click Save.</div>
        ) : (
          <div className="strategy-list">
            {savedStrategies.data.strategies.map((strategy) => (
              <StrategyCard
                key={strategy.strategy_id}
                strategy={strategy}
                onLoad={loadSavedStrategy}
                onDelete={deleteSavedStrategy}
                loading={strategyAction.loading}
              />
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function StrategyCard({ strategy, onLoad, onDelete, loading }) {
  const positions = strategy.positions ?? [];
  const date = strategy.updated_at ? String(strategy.updated_at).slice(0, 10) : null;

  return (
    <div className="strategy-item">
      <div className="strategy-item-header">
        <div className="strategy-item-meta">
          <strong>{strategy.name || 'Unnamed'}</strong>
          {strategy.underlying && <span className="source-pill live">{strategy.underlying}</span>}
          <span className="strategy-item-pos-count">{strategy.position_count} position{strategy.position_count !== 1 ? 's' : ''}</span>
        </div>
        {date && <span className="strategy-item-date">{date}</span>}
      </div>

      {strategy.description && <p className="strategy-item-desc">{strategy.description}</p>}

      {positions.length > 0 && (
        <div className="table-wrap strategy-item-table">
          <table>
            <thead>
              <tr>
                <th>Label</th>
                <th>Type</th>
                <th>Strike K</th>
                <th>T (yr)</th>
                <th>σ (%)</th>
                <th>Qty</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos, index) => (
                <tr key={index}>
                  <td>{pos.label ?? '—'}</td>
                  <td style={{ textTransform: 'capitalize' }}>{pos.option_type ?? '—'}</td>
                  <td>{formatNumber(pos.strike, 0)}</td>
                  <td>{formatNumber(pos.maturity, 2)}</td>
                  <td>{pos.sigma != null ? formatNumber(pos.sigma * 100, 1) : '—'}</td>
                  <td className={pos.quantity < 0 ? 'cell-bad' : 'cell-good'}>
                    {pos.quantity != null ? (pos.quantity > 0 ? `+${pos.quantity}` : String(pos.quantity)) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="strategy-item-footer">
        <button className="primary-button" type="button" onClick={() => onLoad(strategy.strategy_id)} disabled={loading}>
          Load
        </button>
        <button className="secondary-button danger-button" type="button" onClick={() => onDelete(strategy.strategy_id)} disabled={loading}>
          Delete
        </button>
      </div>
    </div>
  );
}

function PricingCard({ optionType, data, selected, onSelect }) {
  const greeksData = data?.greeks ?? {};
  return (
    <button className={`pricing-card ${selected ? 'selected' : ''}`} type="button" onClick={onSelect}>
      <span>{optionType.toUpperCase()}</span>
      <strong>{formatNumber(data?.price, 4)}</strong>
      <div className="mini-greek-grid">
        <em>Δ {formatNumber(greeksData.delta, 4)}</em>
        <em>Γ {formatNumber(greeksData.gamma, 6)}</em>
        <em>ν {formatNumber(greeksData.vega, 4)}</em>
        <em>θ {formatNumber(greeksData.theta, 4)}</em>
      </div>
    </button>
  );
}

function ScenarioMatrix({ rows }) {
  if (!rows.length) return <div className="table-empty">Scenario data unavailable.</div>;
  const spotShocks = uniqueSorted(rows, 'Spot shock');
  const volShocks = uniqueSorted(rows, 'Vol shock');
  const valueFor = (spotShock, volShock) =>
    rows.find((row) => row['Spot shock'] === spotShock && row['Vol shock'] === volShock)?.['P&L (full)'];

  return (
    <div className="scenario-wrap">
      <table className="scenario-table">
        <thead>
          <tr>
            <th>Spot \ Vol</th>
            {volShocks.map((volShock) => (
              <th key={volShock}>{volShock}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spotShocks.map((spotShock) => (
            <tr key={spotShock}>
              <th>{spotShock}</th>
              {volShocks.map((volShock) => {
                const value = valueFor(spotShock, volShock);
                return (
                  <td key={volShock} className={value >= 0 ? 'cell-good' : 'cell-bad'}>
                    {formatEuro(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BacktestChart({ data }) {
  const rows = Array.isArray(data) ? data : data?.rows ?? [];
  const coverage = Array.isArray(data) ? null : data?.coverage;
  if (!rows.length) return <div className="table-empty">Run a backtest after adding portfolio positions.</div>;
  return (
    <>
      {coverage?.note && <Insight>{coverage.note}</Insight>}
      <Plot
        data={[
          {
            type: 'scatter',
            mode: 'lines',
            x: rows.map((row) => row.Date),
            y: rows.map((row) => row['P&L (full)']),
            name: 'P&L full',
            line: { color: '#4b9bd8', width: 2 },
          },
          {
            type: 'scatter',
            mode: 'lines',
            x: rows.map((row) => row.Date),
            y: rows.map((row) => row['P&L (Greeks)']),
            name: 'P&L Greeks approx',
            line: { color: '#d9a441', width: 2 },
          },
          {
            type: 'scatter',
            mode: 'lines',
            x: rows.map((row) => row.Date),
            y: rows.map((row) => row.Error),
            name: 'Error',
            line: { color: '#dc6b59', width: 2 },
          },
        ]}
        layout={{ ...plotLayout, height: 360, yaxis: { title: 'EUR' } }}
        config={plotConfig}
        useResizeHandler
        className="plot"
      />
      <Plot
        data={[
          {
            type: 'bar',
            x: rows.map((row) => row.Date),
            y: rows.map((row) => row['Delta P&L']),
            name: 'Delta',
            marker: { color: '#6ab7ff' },
          },
          {
            type: 'bar',
            x: rows.map((row) => row.Date),
            y: rows.map((row) => row['Gamma P&L']),
            name: 'Gamma',
            marker: { color: '#66d4c3' },
          },
          {
            type: 'bar',
            x: rows.map((row) => row.Date),
            y: rows.map((row) => row['Vega P&L']),
            name: 'Vega',
            marker: { color: '#d8b35d' },
          },
          {
            type: 'bar',
            x: rows.map((row) => row.Date),
            y: rows.map((row) => row['Theta P&L']),
            name: 'Theta',
            marker: { color: '#ef7d70' },
          },
        ]}
        layout={{ ...plotLayout, height: 300, barmode: 'relative', yaxis: { title: 'Greek contribution EUR' } }}
        config={plotConfig}
        useResizeHandler
        className="plot"
      />
      <DataTable
        rows={rows}
        columns={[
          { key: 'Date' },
          { key: 'Spot', format: (value) => formatNumber(value) },
          { key: 'P&L (full)', format: (value) => formatEuro(value) },
          { key: 'P&L (Greeks)', label: 'P&L Greeks approx', format: (value) => formatEuro(value) },
          { key: 'Delta P&L', format: (value) => formatEuro(value) },
          { key: 'Gamma P&L', format: (value) => formatEuro(value) },
          { key: 'Vega P&L', format: (value) => formatEuro(value) },
          { key: 'Theta P&L', format: (value) => formatEuro(value) },
          { key: 'Error', format: (value) => formatEuro(value) },
          { key: 'Historical Vol Proxy', label: 'Hist vol proxy', format: (value) => (value === null || value === undefined ? '—' : `${formatNumber(value, 2)}%`) },
          { key: 'Current Vol Proxy', label: 'Current vol proxy', format: (value) => (value === null || value === undefined ? '—' : `${formatNumber(value, 2)}%`) },
          { key: 'Data Quality' },
        ]}
        maxHeight={260}
      />
    </>
  );
}

function OrdersView({ bootstrap }) {
  const preview = useResource(() => apiGet('/api/orders/preview'), [], true);
  const [orderResult, setOrderResult] = useState({
    validation: null,
    dryRun: null,
    submit: null,
    lastAction: null,
    loading: false,
    error: null,
  });
  const [ticket, setTicket] = useState({
    underlying: bootstrap?.index?.symbol ?? 'ESTX50',
    side: 'BUY',
    quantity: 1,
    orderType: 'LIMIT',
    limitPrice: 5000,
  });

  useEffect(() => {
    if (bootstrap?.index?.symbol) {
      setTicket((current) => ({ ...current, underlying: bootstrap.index.symbol }));
    }
  }, [bootstrap?.index?.symbol]);

  const runOrderAction = async (kind) => {
    setOrderResult((current) => ({ ...current, loading: true, error: null }));
    try {
      const path = kind === 'dryRun' ? '/api/orders/dry-run' : kind === 'submit' ? '/api/orders/submit' : '/api/orders/validate';
      const data = await apiPost(path, ticket);
      setOrderResult((current) => ({ ...current, [kind]: data, lastAction: kind, loading: false, error: null }));
    } catch (error) {
      setOrderResult((current) => ({ ...current, loading: false, error }));
    }
  };

  const activeValidation =
    orderResult.lastAction === 'dryRun'
      ? orderResult.dryRun?.validation
      : orderResult.lastAction === 'submit'
        ? orderResult.submit?.validation
        : orderResult.validation;
  const validationRows = [
    ...(activeValidation?.errors ?? []).map((item) => ({
      Type: 'Error',
      Code: item,
    })),
    ...(activeValidation?.warnings ?? []).map((item) => ({
      Type: 'Warning',
      Code: item,
    })),
  ];

  return (
    <div className="view-stack">
      <Panel title="Account overview" icon={Wallet}>
        {preview.loading && !preview.data ? (
          <LoadingBlock label="Loading account preview" />
        ) : (
          <div className="metric-grid four">
            <MetricTile label="Account type" value="Paper" tone="warn" />
            <MetricTile label="Routing" value={preview.data?.routingEnabled ? 'Live' : 'Disabled'} tone={preview.data?.routingEnabled ? 'bad' : 'good'} />
            <MetricTile label="Open orders" value={formatNumber(preview.data?.openOrders?.length ?? 0, 0)} />
            <MetricTile label="Safety version" value={preview.data?.safetyVersion ?? '—'} />
          </div>
        )}
        <Insight>Real broker routing is locked off. Use Validate to check the ticket, Dry-run to simulate submission — no order reaches the broker.</Insight>
      </Panel>

      <Panel title="Order ticket preview" icon={Send}>
        <div className="form-grid">
          <Field label="Underlying">
            <input value={ticket.underlying} onChange={(event) => setTicket((v) => ({ ...v, underlying: event.target.value }))} />
          </Field>
          <Field label="Side">
            <Segmented value={ticket.side} options={['BUY', 'SELL']} onChange={(side) => setTicket((v) => ({ ...v, side }))} />
          </Field>
          <Field label="Quantity">
            <input type="number" value={ticket.quantity} onChange={(event) => setTicket((v) => ({ ...v, quantity: Number(event.target.value) }))} />
          </Field>
          <Field label="Order type">
            <Segmented value={ticket.orderType} options={['LIMIT', 'MARKET']} onChange={(orderType) => setTicket((v) => ({ ...v, orderType }))} />
          </Field>
          {ticket.orderType === 'LIMIT' && (
            <Field label="Limit price">
              <input type="number" value={ticket.limitPrice} onChange={(event) => setTicket((v) => ({ ...v, limitPrice: Number(event.target.value) }))} />
            </Field>
          )}
        </div>
        <div className="action-row">
          <button className="secondary-button" type="button" onClick={() => runOrderAction('validation')} disabled={orderResult.loading}>
            <ShieldCheck size={16} />
            Validate
          </button>
          <button className="primary-button" type="button" onClick={() => runOrderAction('dryRun')} disabled={orderResult.loading}>
            <Play size={16} />
            Dry-run
          </button>
          <button className="secondary-button disabled-button" type="button" disabled>
            <Send size={16} />
            Live routing disabled
          </button>
        </div>
        {orderResult.error && <ErrorBlock error={orderResult.error} />}
        {activeValidation && (
          <>
            <div className="metric-grid four">
              <MetricTile label="Ticket" value={activeValidation.valid ? 'Valid' : 'Rejected'} tone={activeValidation.valid ? 'good' : 'bad'} />
              <MetricTile label="Routing" value={activeValidation.routingEnabled ? 'Enabled' : 'Disabled'} tone="warn" />
              <MetricTile label="Errors" value={formatNumber(activeValidation.errors?.length ?? 0, 0)} tone={activeValidation.errors?.length ? 'bad' : 'good'} />
              <MetricTile label="Warnings" value={formatNumber(activeValidation.warnings?.length ?? 0, 0)} tone={activeValidation.warnings?.length ? 'warn' : 'good'} />
            </div>
            <DataTable rows={validationRows} columns={[{ key: 'Type' }, { key: 'Code' }]} maxHeight={200} />
          </>
        )}
        {orderResult.dryRun && (
          <>
            <Insight>
              <strong>Dry-run {orderResult.dryRun.dryRunId}</strong> · {orderResult.dryRun.createdAt?.slice(0, 19).replace('T', ' ')} UTC ·{' '}
              <span style={{ color: orderResult.dryRun.status === 'accepted_for_preview' ? 'var(--good)' : 'var(--bad)' }}>
                {orderResult.dryRun.status}
              </span>
              {' '}— {orderResult.dryRun.message}
            </Insight>
            {orderResult.dryRun.validation?.normalizedTicket && (
              <DataTable
                rows={Object.entries(orderResult.dryRun.validation.normalizedTicket).map(([field, value]) => ({
                  Field: field.replace(/([A-Z])/g, ' $1').trim(),
                  Value: value ?? '—',
                }))}
                columns={[{ key: 'Field' }, { key: 'Value' }]}
                maxHeight={200}
              />
            )}
          </>
        )}
      </Panel>

      <Panel title="Open orders" icon={Database}>
        {preview.loading && !preview.data ? (
          <LoadingBlock label="Loading orders" />
        ) : preview.data?.openOrders?.length ? (
          <DataTable
            rows={preview.data.openOrders}
            columns={[{ key: 'Order ID' }, { key: 'Symbol' }, { key: 'Side' }, { key: 'Qty' }, { key: 'Type' }, { key: 'Status' }]}
          />
        ) : (
          <div className="table-empty">No open orders — order routing is disabled, so no orders can be placed via this platform.</div>
        )}
      </Panel>

      <Panel title="Positions" icon={Layers3}>
        {preview.loading && !preview.data ? (
          <LoadingBlock label="Loading positions" />
        ) : preview.data?.positions?.length ? (
          <DataTable
            rows={preview.data.positions}
            columns={[
              { key: 'Symbol' },
              { key: 'Qty' },
              { key: 'Avg Price', format: (v) => formatNumber(v, 2) },
              { key: 'Market Price', format: (v) => formatNumber(v, 2) },
              { key: 'PnL', format: (v) => formatEuro(v), className: (v) => (v >= 0 ? 'cell-good' : 'cell-bad') },
            ]}
          />
        ) : (
          <div className="table-empty">No positions in the paper account — place a paper trade in IBKR TWS to see positions here.</div>
        )}
      </Panel>
    </div>
  );
}

function CheckBadge({ status }) {
  return <span className={`quality-badge ${status ?? 'unknown'}`}>{status ?? 'unknown'}</span>;
}

function ValidationCards({ checks = [] }) {
  if (!checks.length) return <div className="table-empty">No validation checks available.</div>;
  return (
    <div className="validation-grid">
      {checks.map((check) => (
        <article key={check.name} className={`validation-card ${check.status}`}>
          <div>
            <CheckBadge status={check.status} />
            <strong>{check.name.replaceAll('_', ' ')}</strong>
          </div>
          <span>{typeof check.metric === 'number' ? formatNumber(check.metric, 3) : check.metric ?? '—'}</span>
          <em>{check.threshold}</em>
        </article>
      ))}
    </div>
  );
}

function OperationsView() {
  const summary = useResource(() => apiGet('/api/operations/summary'), [], true);
  const latestRun = summary.data?.latestRun ?? {};
  const manifest = latestRun.manifest ?? {};
  const validation = summary.data?.validation ?? {};
  const artifactRows = Object.entries(manifest.artifacts ?? {}).map(([name, path]) => ({ Name: name, Path: path }));

  const reload = () => {
    summary.reload();
  };

  return (
    <div className="view-stack">
      <div className="toolbar">
        <div className="control-row">
          <span className="toolbar-title">Operations readiness</span>
          {validation.status && <CheckBadge status={validation.status} />}
        </div>
        <RefreshButton onClick={reload} loading={summary.loading} />
      </div>

      <Panel title="Run health" icon={ShieldCheck}>
        {summary.error && <ErrorBlock error={summary.error} />}
        {summary.loading && !summary.data ? (
          <LoadingBlock label="Loading operations summary" />
        ) : (
          <>
            <div className="metric-grid six">
              <MetricTile label="Overall" value={validation.status ?? '—'} tone={validation.status === 'pass' ? 'good' : validation.status === 'warn' ? 'warn' : 'bad'} />
              <MetricTile label="Pass" value={formatNumber(validation.summary?.pass, 0)} tone="good" />
              <MetricTile label="Warn" value={formatNumber(validation.summary?.warn, 0)} tone={validation.summary?.warn ? 'warn' : 'good'} />
              <MetricTile label="Fail" value={formatNumber(validation.summary?.fail, 0)} tone={validation.summary?.fail ? 'bad' : 'good'} />
              <MetricTile label="Routing" value={summary.data?.routingEnabled ? 'Enabled' : 'Disabled'} tone="warn" />
              <MetricTile label="Run" value={manifest.run_id?.slice(0, 17) ?? '—'} />
            </div>
            <DataTable
              rows={[
                { Label: 'Created at', Value: manifest.created_at },
                { Label: 'Trade date', Value: manifest.trade_date },
                { Label: 'Quote QC', Value: manifest.quote_qc_version },
                { Label: 'Surface model', Value: manifest.surface_model_version },
                { Label: 'Order safety', Value: summary.data?.orderSafetyVersion },
                { Label: 'Run path', Value: manifest.run_path },
              ]}
              columns={[{ key: 'Label' }, { key: 'Value' }]}
              maxHeight={280}
            />
          </>
        )}
      </Panel>

      <Panel title="Validation checks" icon={CheckCircle2}>
        <ValidationCards checks={validation.checks ?? []} />
        <DataTable
          rows={validation.checks ?? []}
          columns={[
            { key: 'name', label: 'Check' },
            { key: 'status', label: 'Status', format: (value) => <CheckBadge status={value} /> },
            { key: 'metric', label: 'Metric', format: (value) => (typeof value === 'number' ? formatNumber(value, 3) : value ?? '—') },
            { key: 'threshold', label: 'Threshold' },
            { key: 'detail', label: 'Detail' },
          ]}
        />
      </Panel>

      <Panel title="Artifacts" icon={Database}>
        <DataTable rows={artifactRows} columns={[{ key: 'Name' }, { key: 'Path' }]} maxHeight={280} />
      </Panel>
    </div>
  );
}

function SurfaceHealthStrip({ diagnostics, validRows, maturities }) {
  const grid = diagnostics.displayGrid ?? {};
  const calendarBreaks = diagnostics.calendar?.violationCount ?? 0;
  return (
    <section className="surface-strip">
      <MetricTile label="Accepted points" value={formatNumber(diagnostics.acceptedPoints ?? validRows.length, 0)} tone="good" />
      <MetricTile label="Rejected rows" value={formatNumber(diagnostics.rejectedRows, 0)} tone={diagnostics.rejectedRows ? 'warn' : 'good'} />
      <MetricTile label="Maturities" value={formatNumber(maturities.length, 0)} />
      <MetricTile label="Common strikes" value={formatNumber(grid.strikeCount, 0)} tone={(grid.strikeCount ?? 0) >= 5 ? 'good' : 'warn'} />
      <MetricTile label="Calendar breaks" value={formatNumber(calendarBreaks, 0)} tone={calendarBreaks ? 'bad' : 'good'} />
    </section>
  );
}

function SurfaceView({ bootstrap }) {
  const [notional, setNotional] = useState(10);
  const spot = useResource(() => apiGet('/api/spot'), [], Boolean(bootstrap));
  const options = useResource(() => apiGet('/api/options', { notional }), [notional], Boolean(bootstrap));
  const surface = useResource(() => apiGet('/api/surface', { notional }), [notional], Boolean(bootstrap));
  const rows = options.data ?? [];
  const validRows = surface.data?.ivPoints?.length ? surface.data.ivPoints : rows.filter(isSurfaceIvRow);
  const maturities = uniqueSorted(validRows, 'Maturity');
  const surfaceSpot = surface.data?.spot ?? spot.data?.last ?? spot.data?.close ?? 5000;
  const diagnostics = surface.data?.diagnostics ?? {};
  const ivValues = validRows.map((row) => Number(row['IV %'])).filter(Number.isFinite);
  const maxIv = ivValues.length ? Math.max(...ivValues) : null;
  const [selectedMaturity, setSelectedMaturity] = useState('');

  useEffect(() => {
    if (!selectedMaturity && maturities.length) setSelectedMaturity(maturities[0]);
  }, [maturities, selectedMaturity]);

  const smileRows = validRows
    .filter((row) => row.Maturity === selectedMaturity)
    .sort((a, b) => Number(a.Strike) - Number(b.Strike));
  const termRows = maturities.map((maturity) => selectAtmTermPoint(validRows, maturity, surfaceSpot));

  return (
    <div className="view-stack">
      <div className="toolbar">
        <div className="control-row">
          <Field label="Multiplier">
            <input type="number" min="1" value={notional} onChange={(event) => setNotional(Number(event.target.value))} />
          </Field>
        </div>
        <RefreshButton
          onClick={() => {
            spot.reload();
            options.reload();
            surface.reload();
          }}
          loading={spot.loading || options.loading || surface.loading}
        />
      </div>

      <SurfaceHealthStrip diagnostics={diagnostics} validRows={validRows} maturities={maturities} />

      <Panel title="3D volatility surface" icon={Waves}>
        {surface.error && <ErrorBlock error={surface.error} />}
        {options.error && <ErrorBlock error={options.error} />}
        {surface.loading && !surface.data ? (
          <LoadingBlock label="Loading surface" />
        ) : (
          <SurfaceChart surfaceData={surface.data} rows={rows} height={620} />
        )}
      </Panel>

      <div className="split-grid">
        <Panel title="Volatility smile" icon={LineChart}>
          <div className="control-row">
            <Field label="Maturity">
              <select value={selectedMaturity} onChange={(event) => setSelectedMaturity(event.target.value)}>
                {maturities.map((maturity) => (
                  <option key={maturity} value={maturity}>{fmtMaturity(maturity)}</option>
                ))}
              </select>
            </Field>
          </div>
          <SmileChart rows={smileRows} />
        </Panel>

        <Panel title="ATM term structure" icon={BarChart3}>
          <TermChart rows={termRows} />
        </Panel>
      </div>

      <Panel title="Surface statistics" icon={Database}>
        <div className="metric-grid six">
          <MetricTile label="Accepted" value={formatNumber(diagnostics.acceptedPoints ?? validRows.length, 0)} />
          <MetricTile label="Rejected" value={formatNumber(diagnostics.rejectedRows, 0)} />
          <MetricTile label="Maturities" value={formatNumber(maturities.length, 0)} />
          <MetricTile label="Calendar breaks" value={formatNumber(diagnostics.calendar?.violationCount, 0)} />
          <MetricTile label="Average IV" value={`${formatNumber(mean(validRows.map((row) => row['IV %'])), 2)}%`} />
          <MetricTile label="Max IV" value={`${formatNumber(maxIv, 2)}%`} />
        </div>
        <DataTable
          rows={validRows}
          columns={[
            { key: 'Maturity', format: (value) => fmtMaturity(value) },
            { key: 'Strike', format: (value) => formatNumber(value, 0) },
            { key: 'Type' },
            { key: 'IV %', label: 'IV', format: (value) => `${formatNumber(value, 2)}%` },
            { key: 'Mid', format: (value) => formatNumber(value) },
            { key: 'Quote Quality' },
            { key: 'QC Status' },
            { key: 'QC Reasons', format: (value) => (Array.isArray(value) && value.length ? value.join(', ') : '—') },
            { key: 'IV Source', format: (value) => <span className={`source-pill ${value === 'IBKR' ? 'live' : 'calc'}`}>{value ?? '—'}</span> },
            { key: 'IV Status' },
            { key: 'IV Reason' },
            { key: 'Forward', format: (value) => formatNumber(value) },
            { key: 'Forward Source' },
            { key: 'Log Moneyness', format: (value) => formatNumber(value, 4) },
            { key: 'Total Variance', format: (value) => formatNumber(value, 6) },
          ]}
        />
      </Panel>
    </div>
  );
}

function mean(values) {
  const clean = values.map(Number).filter(Number.isFinite);
  if (!clean.length) return null;
  return clean.reduce((sum, value) => sum + value, 0) / clean.length;
}

function hasReliableQuote(row) {
  const quality = row['Quote Quality'];
  return quality === 'tight' || quality === 'wide';
}

function selectAtmTermPoint(rows, maturity, spot) {
  const maturityRows = rows.filter((row) => row.Maturity === maturity && hasReliableQuote(row));
  const atmRows = maturityRows.filter((row) => String(row.Type ?? '').startsWith('ATM'));
  const sourceRows = atmRows.length ? atmRows : maturityRows;

  if (!sourceRows.length) {
    return { Maturity: maturity, 'ATM IV': null, Source: 'skipped' };
  }

  const bestDistance = Math.min(...sourceRows.map((row) => Math.abs(Number(row.Strike) - spot)));
  const bestRows = sourceRows.filter((row) => Math.abs(Number(row.Strike) - spot) === bestDistance);
  const ivs = bestRows.map((row) => Number(row['IV %'])).filter(Number.isFinite);

  return {
    Maturity: maturity,
    'ATM IV': mean(ivs),
    Source: atmRows.length ? 'ATM call/put' : 'nearest liquid',
    Rows: bestRows.length,
  };
}

function SmileChart({ rows }) {
  if (!rows.length) return <div className="table-empty">No smile data for this maturity.</div>;
  return (
    <Plot
      data={[
        {
          type: 'scatter',
          mode: 'lines+markers',
          x: rows.map((row) => row.Strike),
          y: rows.map((row) => row['IV %']),
          name: 'IV smile',
          line: { color: '#4b9bd8', width: 2 },
        },
      ]}
      layout={{ ...plotLayout, height: 380, xaxis: { title: 'Strike' }, yaxis: { title: 'IV (%)' } }}
      config={plotConfig}
      useResizeHandler
      className="plot"
    />
  );
}

function TermChart({ rows }) {
  const clean = rows.filter((row) => row['ATM IV'] !== null && row['ATM IV'] !== undefined);
  if (!clean.length) return <div className="table-empty">No term structure data available.</div>;
  return (
    <Plot
      data={[
        {
          type: 'scatter',
          mode: 'lines+markers',
          x: clean.map((row) => fmtMaturity(row.Maturity)),
          y: clean.map((row) => row['ATM IV']),
          name: 'ATM IV',
          text: clean.map((row) => row.Source),
          hovertemplate: 'Maturity=%{x}<br>ATM IV=%{y:.2f}%<br>%{text}<extra></extra>',
          line: { color: '#d9a441', width: 2 },
        },
      ]}
      layout={{ ...plotLayout, height: 380, xaxis: { title: 'Maturity' }, yaxis: { title: 'ATM IV (%)' } }}
      config={plotConfig}
      useResizeHandler
      className="plot"
    />
  );
}

export default App;
