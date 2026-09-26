<template>
  <section class="page" data-module="instrument">
    <header class="page-head">
      <div>
        <h2>仪器设备管理</h2>
        <p class="page-desc">临期自动转待检定、超期在用一律拦下，临期阈值按保管人所在实验室区分。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记仪器</button>
        <button class="btn" type="button" @click="refreshAll">按新口径重标</button>
        <button class="btn" type="button" @click="exportRows">导出仪器设备清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>仪器编号</span>
        <input v-model="filters.keyword" placeholder="按仪器编号检索" />
      </label>
      <label class="filter-item">
        <span>仪器状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="rowClass(row)">
          <td v-for="column in columns" :key="column">{{ displayCell(row, column) }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openCalibration(row)">登记检定</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无仪器设备数据，可先登记仪器</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条仪器设备记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
    </footer>

    <div v-if="calibrationTarget" class="modal-mask" @click.self="closeCalibration">
      <form class="modal-card" @submit.prevent="submitCalibration">
        <h3 class="modal-title">登记检定 — {{ calibrationTarget['仪器编号'] }}</h3>
        <label class="form-row">
          <span>检定日期</span>
          <input v-model="calibrationForm['检定日期']" type="date" required />
        </label>
        <label class="form-row">
          <span>下次检定日</span>
          <input v-model="calibrationForm['下次检定日']" type="date" required />
        </label>
        <label class="form-row">
          <span>检定机构</span>
          <input v-model="calibrationForm['检定机构']" placeholder="如：省计量科学研究院" />
        </label>
        <label class="form-row">
          <span>记录人</span>
          <input v-model="calibrationForm['记录人']" />
        </label>
        <p v-if="calibrationError" class="error-text">{{ calibrationError }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="submit">保存检定记录</button>
          <button class="btn ghost" type="button" @click="closeCalibration">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/instrument'
const columns = ["仪器编号", "仪器名称", "规格型号", "所属实验室", "检定日期", "下次检定日", "保管人", "仪器状态", "检定结论", "距到期天数"]
const actions = ["办理检定", "送修", "停用仪器"]
const statuses = ["正常", "待检定", "维修中", "已停用"]

const stats = ref([
  { label: '正常仪器', value: 0 },
  { label: '待检定仪器', value: 0 },
  { label: '已超期仪器', value: 0 },
  { label: '维修中仪器', value: 0 },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', status: '' })

const calibrationTarget = ref<Row | null>(null)
const calibrationForm = ref<Record<string, string>>({})
const calibrationError = ref('')

function rowClass(row: Row) {
  return {
    'row-overdue': row['检定结论'] === '已超期',
    'row-due': row['检定结论'] === '临期待检',
  }
}

function displayCell(row: Row, column: string) {
  if (column === '距到期天数') {
    const days = row['距下次检定天数']
    return days === null || days === undefined ? '—' : `${days} 天`
  }
  return row[column] ?? '—'
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '仪器登记入口尚未接入审批流'
}

function openCalibration(row: Row) {
  calibrationTarget.value = row
  calibrationForm.value = { 检定日期: '', 下次检定日: '', 检定机构: '', 记录人: '' }
  calibrationError.value = ''
}

function closeCalibration() {
  calibrationTarget.value = null
  calibrationError.value = ''
}

async function parsePayload(response: Response) {
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message ?? payload.detail ?? '仪器设备操作失败')
  }
  return payload
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await parsePayload(response)
    noticeMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '仪器设备操作失败'
  }
}

async function submitCalibration() {
  calibrationError.value = ''
  try {
    const response = await request(`${ENDPOINT}/calibrations`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          仪器编号: calibrationTarget.value?.['仪器编号'],
          ...calibrationForm.value,
        },
      }),
    })
    const payload = await parsePayload(response)
    closeCalibration()
    errorMessage.value = ''
    noticeMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    calibrationError.value = error instanceof Error ? error.message : '检定记录保存失败'
  }
}

async function refreshAll() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/refresh`, { method: 'POST' })
    const payload = await parsePayload(response)
    noticeMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重标失败'
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (!response.ok) return
    const data = await response.json()
    stats.value = [
      { label: '正常仪器', value: data['正常'] ?? 0 },
      { label: '待检定仪器', value: data['待检定'] ?? 0 },
      { label: '已超期仪器', value: data['已超期'] ?? 0 },
      { label: '维修中仪器', value: data['维修中'] ?? 0 },
    ]
  } catch {
    // 统计卡片失败不挡列表
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('仪器列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadSummary()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '仪器设备列表读取失败'
  }
}

onMounted(reload)
</script>
