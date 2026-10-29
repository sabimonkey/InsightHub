import type { ThemeConfig } from 'antd'

export const ihAntdTheme: ThemeConfig = {
  token: {
    colorPrimary: '#0736FE',
    colorText: '#171717',
    colorTextSecondary: '#606060',
    colorTextTertiary: '#858585',
    colorBgBase: '#F5F5F3',
    colorBgContainer: '#FFFFFF',
    colorBgLayout: '#F5F5F3',
    colorBorder: '#D7D7D4',
    colorBorderSecondary: '#E7E7E4',
    borderRadius: 10,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
  },
  components: {
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      contentFontSizeSM: 13,
      controlHeightSM: 30,
      colorPrimary: '#0736FE',
      colorPrimaryHover: '#052EE0',
      colorPrimaryActive: '#0427C2',
      colorTextLightSolid: '#FFFFFF',
    },
    Tag: {
      defaultBg: '#EEEEEC',
      defaultColor: '#606060',
    },
    Card: {
      colorBgContainer: '#FFFFFF',
    },
    Modal: {
      contentBg: '#FFFFFF',
    },
  },
}
