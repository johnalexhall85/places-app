const MONEY_SCALE = 2;

function cleanDecimal(value) {
  const token = String(value ?? "").trim();
  if (!/^-?(?:\d+|\d*\.\d+)$/.test(token)) return null;
  return token;
}

export function decimalToScaledBigInt(value, scale = MONEY_SCALE) {
  const token = cleanDecimal(value);
  if (token === null) return null;
  const negative = token.startsWith("-");
  const unsigned = negative ? token.slice(1) : token;
  const [wholeRaw, fractionRaw = ""] = unsigned.split(".");
  const whole = wholeRaw || "0";
  const fraction = `${fractionRaw}${"0".repeat(scale)}`.slice(0, scale);
  const scaled = BigInt(whole) * (10n ** BigInt(scale)) + BigInt(fraction || "0");
  return negative ? -scaled : scaled;
}

export function scaledBigIntToDecimalString(value, scale = MONEY_SCALE) {
  const scaled = typeof value === "bigint" ? value : BigInt(value);
  const negative = scaled < 0n;
  const divisor = 10n ** BigInt(scale);
  const absolute = negative ? -scaled : scaled;
  const whole = absolute / divisor;
  const fraction = String(absolute % divisor).padStart(scale, "0");
  return `${negative ? "-" : ""}${whole}.${fraction}`;
}

export function normalizeMoneyString(value) {
  const scaled = decimalToScaledBigInt(value, MONEY_SCALE);
  return scaled === null ? null : scaledBigIntToDecimalString(scaled, MONEY_SCALE);
}

export function compareMoneyStrings(a, b) {
  const left = decimalToScaledBigInt(a, MONEY_SCALE);
  const right = decimalToScaledBigInt(b, MONEY_SCALE);
  if (left === null && right === null) return 0;
  if (left === null) return -1;
  if (right === null) return 1;
  if (left === right) return 0;
  return left > right ? 1 : -1;
}

export function sumMoneyStrings(values) {
  const total = values.reduce((sum, value) => {
    const scaled = decimalToScaledBigInt(value, MONEY_SCALE);
    return scaled === null ? sum : sum + scaled;
  }, 0n);
  return scaledBigIntToDecimalString(total, MONEY_SCALE);
}

function withCommas(value) {
  return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

export function formatCurrencyFromDecimalString(value) {
  const scaled = decimalToScaledBigInt(value, MONEY_SCALE);
  if (scaled === null) return "Not available";
  const negative = scaled < 0n;
  const absolute = negative ? -scaled : scaled;
  const dollars = absolute / 100n;
  const cents = String(absolute % 100n).padStart(2, "0");
  return `${negative ? "-$" : "$"}${withCommas(dollars)}.${cents}`;
}

export function formatPercentFromDecimalString(value, digits = 1) {
  if (value === null || value === undefined) return "Not available";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "Not available";
  const normalized = Object.is(numeric, -0) ? 0 : numeric;
  return `${normalized.toFixed(digits)}%`;
}

export function decimalStringToNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

export function isZeroMoney(value) {
  return compareMoneyStrings(value, "0.00") === 0;
}

export function escapeCsvCell(value) {
  const text = String(value ?? "");
  if (!/[",\n\r]/.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

export function rowsToCsv(rows) {
  return rows.map((row) => row.map(escapeCsvCell).join(",")).join("\r\n");
}
