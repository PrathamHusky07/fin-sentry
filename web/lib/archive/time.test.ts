import { describe, expect, it } from "vitest";
import { micros, minuteStart, utcZ } from "@/lib/archive/time";

describe("utcZ", () => {
  it("writes the zone as Z and pads the fraction to six digits, as pydantic does", () => {
    expect(utcZ("2026-10-20T21:53:33.2022+00:00")).toBe(
      "2026-10-20T21:53:33.202200Z",
    );
    expect(utcZ("2026-10-08T00:20:45.824760+00:00")).toBe(
      "2026-10-08T00:20:45.824760Z",
    );
  });

  it("drops a fraction that is all zeros and keeps a whole second whole", () => {
    expect(utcZ("2026-10-20T21:53:33.000000+00:00")).toBe(
      "2026-10-20T21:53:33Z",
    );
    expect(utcZ("2026-10-01T12:00:00Z")).toBe("2026-10-01T12:00:00Z");
  });
});

describe("micros", () => {
  it("orders two instants less than a millisecond apart", () => {
    expect(micros("2026-10-08T00:20:45.824761+00:00")).toBeGreaterThan(
      micros("2026-10-08T00:20:45.824760+00:00"),
    );
  });

  it("reads a short fraction as the digits it has", () => {
    expect(micros("2026-10-20T21:53:33.2022+00:00")).toBe(
      micros("2026-10-20T21:53:33.202200+00:00"),
    );
  });
});

describe("minuteStart", () => {
  it("floors an instant to its UTC minute", () => {
    expect(
      new Date(minuteStart("2026-10-22T20:00:39.115184+00:00")).toISOString(),
    ).toBe("2026-10-22T20:00:00.000Z");
  });
});
