import type { HelperTask, MistItem } from "./types";

const scene = {
  id: "scene",
  name: "事故現場",
  address: "成功大學光復校區，中正堂東側入口",
  accessNote: "由大學路入口進入，接應者會在路口揮手示意。",
  coordinates: { lat: 22.99939, lng: 120.21802 },
  distanceMeters: 320,
  walkingMinutes: 4,
};

const snapshot = {
  location: scene.address,
  situation: "1 名患者倒地；周圍目前無回報危險",
  treatment: "已通報 119；AED 取件中",
  entrance: scene.accessNote,
  updatedAt: new Date(Date.now() - 20_000).toISOString(),
};

export const demoAedTask: HelperTask = {
  id: "demo-helper",
  incidentId: "demo-incident",
  role: "aed_runner",
  status: "en_route",
  assignmentRevision: 1,
  expiresAt: new Date(Date.now() + 10 * 60_000).toISOString(),
  freshness: "live",
  destination: {
    id: "aed-guardhouse",
    name: "光復校區警衛室 AED",
    address: "台南市東區大學路 1 號，光復校區警衛室",
    accessNote: "面向大學路，進門後向值班人員索取 AED。",
    coordinates: { lat: 22.99884, lng: 120.21692 },
    distanceMeters: 320,
    walkingMinutes: 4,
    availability: "24 小時可取得",
  },
  scene,
  snapshot,
  timeline: [
    {
      id: "task-accepted",
      occurredAt: new Date(Date.now() - 60_000).toISOString(),
      label: "協助者已接受 AED 取件任務",
      source: "helper",
      confirmation: "confirmed",
    },
  ],
};

export const reassignedAed = {
  id: "aed-library",
  name: "成功大學圖書館 AED",
  address: "台南市東區大學路 1 號，總圖書館一樓服務台",
  accessNote: "由正門進入，AED 位於一樓服務台右側。",
  coordinates: { lat: 22.99978, lng: 120.21947 },
  distanceMeters: 410,
  walkingMinutes: 5,
  availability: "目前開放，可由服務台取得",
};

export const demoGreeterTask: HelperTask = {
  ...demoAedTask,
  id: "demo-greeter",
  role: "ambulance_greeter",
  destination: {
    id: "meeting-point",
    name: "大學路入口接應點",
    address: "成功大學光復校區大學路入口",
    accessNote: "抵達入口後留意救護車，並引導至中正堂東側。",
    coordinates: { lat: 22.99792, lng: 120.21646 },
    distanceMeters: 180,
    walkingMinutes: 2,
  },
};

export const demoMist: MistItem[] = [
  { letter: "M", label: "主要狀況", value: "校園內有人突然倒地；原因未確認", confirmed: false },
  { letter: "I", label: "傷勢", value: "未觀察到明顯外傷", confirmed: true },
  { letter: "S", label: "徵象", value: "無反應；呼吸狀態等待再次確認", confirmed: false },
  { letter: "T", label: "已做處置", value: "已通報 119；AED 取件中", confirmed: true },
];

export const demoTimeline = [
  {
    id: "created",
    occurredAt: "2026-09-19T14:02:00+08:00",
    label: "事件建立，位置等待確認",
    source: "system",
    confirmation: "reported",
  },
  {
    id: "called",
    occurredAt: "2026-09-19T14:03:00+08:00",
    label: "使用者回報已撥打 119",
    source: "user",
    confirmation: "reported",
  },
  {
    id: "helper",
    occurredAt: "2026-09-19T14:04:00+08:00",
    label: "AED 取件任務已接受",
    source: "helper",
    confirmation: "confirmed",
  },
] as const;
