import type { Metadata } from "next";
import data from "../../public/report/report.json";
import ReportPage from "./report-page";
import type { Report } from "./report-model";
const report = data as unknown as Report;
export const metadata: Metadata = {
  title:
    report.rounds.find((round) => round.round.id === report.current_round_id)
      ?.manifest.title || "验收报告",
  description: "验收结论、观察记录与证据。",
  icons: { icon: "/favicon.svg" },
};
export default function Page() {
  return <ReportPage report={report} />;
}
