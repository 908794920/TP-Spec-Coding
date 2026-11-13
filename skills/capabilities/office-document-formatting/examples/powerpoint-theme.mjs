// 仅用于没有客户模板的新建演示；既有 deck 应复用原主题，不能全篇重设。
export const powerpointDefaults = {
  slideSize: { width: 1280, height: 720 },
  title: { typeface: "黑体", fontSize: "32pt", color: "tx1" },
  body: { typeface: "宋体", fontSize: "20pt", color: "tx1" },
  note: { typeface: "宋体", fontSize: "14pt", color: "tx2" },
};

export function applyPowerPointTheme(presentation) {
  presentation.theme.defaultFont = "宋体";
  presentation.theme.colorScheme = {
    name: "Conservative Chinese",
    themeColors: {
      accent1: "#1F4E79", accent2: "#595959", accent3: "#808080",
      accent4: "#A6A6A6", accent5: "#D9D9D9", accent6: "#404040",
      bg1: "#FFFFFF", bg2: "#F2F2F2", tx1: "#000000", tx2: "#595959",
      dk1: "#000000", dk2: "#404040", lt1: "#FFFFFF", lt2: "#F2F2F2",
      hlink: "#1F4E79", folHlink: "#595959",
    },
  };
  return powerpointDefaults;
}
