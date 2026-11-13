export const excelNumberFormats = {
  identifier: "@",
  count: "0",
  amount: "#,##0.00",
  percentage: "0.00%",
  date: "yyyy-mm-dd",
};

// 仅用于无既定模板的新建范围；增量编辑沿用原件的同类样式。
export function applyExcelStyles(bodyRange, headerRange) {
  bodyRange.format.font = { name: "SimSun", size: 11, color: "#000000" };
  headerRange.format.font = { name: "SimSun", size: 11, color: "#000000", bold: true };
  headerRange.format.fill = "#E7E6E6";
}
