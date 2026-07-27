import { describe, expect, it } from "vitest";
import {
  compareMoneyStrings,
  escapeCsvCell,
  formatCurrencyFromDecimalString,
  formatPercentFromDecimalString,
  normalizeMoneyString,
  rowsToCsv,
  sumMoneyStrings,
} from "./cdcFundingFormatting";

describe("cdcFundingFormatting", () => {
  it("formats large and negative money values without floating point drift", () => {
    expect(formatCurrencyFromDecimalString("18654414464.47")).toBe("$18,654,414,464.47");
    expect(formatCurrencyFromDecimalString("-44472.16")).toBe("-$44,472.16");
    expect(normalizeMoneyString("12")).toBe("12.00");
  });

  it("compares and sums money strings as scaled integers", () => {
    expect(compareMoneyStrings("100.01", "100.00")).toBe(1);
    expect(compareMoneyStrings("-0.00", "0.00")).toBe(0);
    expect(sumMoneyStrings(["5820366186.77", "681288736.13", "4934414807.93", "7218344733.64"]))
      .toBe("18654414464.47");
  });

  it("formats percentages and escapes CSV cells", () => {
    expect(formatPercentFromDecimalString("31.2010")).toBe("31.2%");
    expect(formatPercentFromDecimalString(null)).toBe("Not available");
    expect(escapeCsvCell('A "quoted", account')).toBe('"A ""quoted"", account"');
    expect(rowsToCsv([["symbol", "name"], ["075-1", "Alpha, Beta"]]))
      .toBe("symbol,name\r\n075-1,\"Alpha, Beta\"");
  });
});
