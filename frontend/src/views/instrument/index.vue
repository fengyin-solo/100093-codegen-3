<template>
  <section class="page" data-module="instrument">
    <header class="page-head">
      <div>
        <h2>仪器设备管理</h2>
        <p class="page-desc">维护仪器，围绕仪器编号、仪器名称、规格型号、所属实验室做登记、筛选与状态流转；检定结论按实验室阈值自动判定。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记仪器</button>
        <button class="btn" type="button" @click="refreshCalibers">按新口径重标</button>
        <button class="btn" type="button" @click="exportRows">导出仪器设备清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="item.tone">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
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
          <td v-for="column in columns" :key="column">
            <span v-if="column === '检定结论'" class="tag" :class="tagClass(row)">{{ row[column] ?? '—' }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
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

    <section v-if="detail" class="detail-panel">
      <header class="detail-head">
        <h3>仪器详情：{{ detail['仪器编号'] }} {{ detail['仪器名称'] }}</h3>
        <button class="btn ghost" type="button" @click="detail = null">收起</button>
      </header>
      <dl class="detail-grid">
        <div v-for="field in detailFields" :key="field" class="detail-item">
          <dt>{{ field }}</dt>
          <dd>
            <span v-if="field === '检定结论'" class="tag" :class="tagClass(detail)">{{ detail[field] ?? '—' }}</span>
            <template v-else>{{ detail[field] ?? '—' }}</template>
          </dd>
        </div>
      </dl>
      <p class="detail-reason">判定依据：{{ detail['结论原因'] }}（适用阈值 {{ detail['适用阈值'] }} 天，日期来源：{{ detail['日期来源'] }}）</p>
      <table class="data-table">
        <thead>
          <tr><th>记录编号</th><th>检定日期</th><th>下次检定日</th><th>检定机构</th><th>检定人</th></tr>
        </thead>
        <tbody>
          <tr v-for="record in calibrationRecords" :key="String(record.id)">
            <td>{{ record['记录编号'] }}</td>
            <td>{{ record['检定日期'] }}</td>
            <td>{{ record['下次检定日'] }}</td>
            <td>{{ record['检定机构'] }}</td>
            <td>{{ record['检定人'] }}</td>
          </tr>
          <tr v-if="!calibrationRecords.length">
            <td colspan="5" class="empty-state">暂无检定记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条仪器设备记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null> & { id?: number }

const ENDPOINT = '/api/instrument'
const columns = ["仪器编号", "仪器名称", "规格型号", "所属实验室", "检定日期", "下次检定日", "距到期天数", "检定结论", "保管人", "仪器状态"]
const actions = ["查看", "办理检定", "送修", "停用仪器"]
const detailFields = ["仪器编号", "仪器名称", "规格型号", "所属实验室", "保管人", "检定日期", "下次检定日", "仪器状态", "检定结论", "距到期天数"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const detail = ref<Row | null>(null)
const conclusionCounts = ref<Record<string, number>>({})

const stats = computed(() => [
  { label: '在检定期内', value: conclusionCounts.value['在检定期内'] ?? 0, tone: '' },
  { label: '临近到期（待检定）', value: conclusionCounts.value['临近到期'] ?? 0, tone: 'warn' },
  { label: '已超期', value: conclusionCounts.value['已超期'] ?? 0, tone: 'danger' },
  { label: '不参与判定（维修/停用）', value: conclusionCounts.value['不参与判定'] ?? 0, tone: '' },
])

const calibrationRecords = computed<Row[]>(() => (detail.value?.['检定记录'] as Row[] | undefined) ?? [])

function todayText(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function rowClass(row: Row): string {
  if (row['检定结论'] === '已超期') return 'row-overdue'
  if (row['检定结论'] === '临近到期') return 'row-due-soon'
  return ''
}

function tagClass(row: Row): string {
  const conclusion = String(row['检定结论'] ?? '')
  if (conclusion === '已超期') return 'danger'
  if (conclusion === '临近到期') return 'warn'
  if (conclusion === '在检定期内') return 'ok'
  return 'muted'
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '仪器登记入口尚未接入审批流'
}

async function refreshCalibers() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/refresh`, { method: 'POST' })
    const payload = await response.json()
    noticeMessage.value = payload.message ?? '已按新口径重标'
    await Promise.all([reload(), reloadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重标失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('仪器详情读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '仪器详情读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  if (action === '查看') {
    await openDetail(row)
    return
  }
  const values: Record<string, string> = { action }
  if (action === '办理检定') {
    const calDay = window.prompt('请输入本次检定日期（YYYY-MM-DD）', todayText())
    if (calDay === null) return
    const nextDay = window.prompt('请输入下次检定日（YYYY-MM-DD）')
    if (nextDay === null) return
    values['检定日期'] = calDay.trim()
    values['下次检定日'] = nextDay.trim()
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      errorMessage.value = payload.message ?? payload.detail ?? '仪器设备动作未生效，请稍后重试'
      return
    }
    noticeMessage.value = payload.message ?? `仪器已${action}`
    await Promise.all([reload(), reloadSummary()])
    if (detail.value && detail.value.id === row.id) {
      await openDetail(row)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '仪器设备操作失败'
  }
}

async function reload() {
  const params = new URLSearchParams()
  const code = (filters.value['仪器编号'] ?? '').trim()
  if (code) {
    params.set('keyword', code)
  }
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('仪器列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '仪器设备列表读取失败'
  }
}

async function reloadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    conclusionCounts.value = payload['结论统计'] ?? {}
  } catch {
    conclusionCounts.value = {}
  }
}

onMounted(() => {
  void reload()
  void reloadSummary()
})
</script>
