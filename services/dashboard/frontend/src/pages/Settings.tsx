import React, { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'react-hot-toast'
import { Settings as SettingsIcon, Moon, Sun, Loader2, Pencil, AlertTriangle, Lock } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/Dialog'
import { Label } from '@/components/ui/Label'
import { Badge } from '@/components/ui/Badge'
import { configApi } from '@/lib/api'
import { Factor, getFactors } from '@/api/factors'
import { cn } from '@/lib/utils'

type Tab = 'general' | 'factors'

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>('general')

  return (
    <div className="space-y-6">
      {/* Header with tabs */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Settings</h1>
          <p className="text-sm text-muted-foreground mt-1">
            시스템 설정 및 트레이딩 팩터 관리
          </p>
        </div>
        <div className="flex gap-1 p-1 bg-white/5 rounded-lg">
          <button
            onClick={() => setActiveTab('general')}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-colors',
              activeTab === 'general'
                ? 'bg-white text-black'
                : 'text-muted-foreground hover:text-white'
            )}
          >
            General
          </button>
          <button
            onClick={() => setActiveTab('factors')}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-colors',
              activeTab === 'factors'
                ? 'bg-white text-black'
                : 'text-muted-foreground hover:text-white'
            )}
          >
            Factors
          </button>
        </div>
      </div>

      {activeTab === 'general' ? <GeneralTab /> : <FactorsTab />}
    </div>
  )
}

function GeneralTab() {
  const queryClient = useQueryClient()

  const { data: configItems, isLoading } = useQuery({
    queryKey: ['config-list'],
    queryFn: configApi.list,
  })

  const [selectedKey, setSelectedKey] = React.useState<string | null>(null)
  const [editValue, setEditValue] = React.useState<string>('')
  const [editDesc, setEditDesc] = React.useState<string>('')
  const [search, setSearch] = React.useState('')
  const [categoryFilter, setCategoryFilter] = React.useState('ALL')

  const updateMutation = useMutation({
    mutationFn: ({ key, value, description }: { key: string; value: any; description?: string }) =>
      configApi.update(key, value, description),
    onSuccess: () => {
      toast.success('저장되었습니다')
      queryClient.invalidateQueries({ queryKey: ['config-list'] })
      setSelectedKey(null)
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || '저장에 실패했습니다')
    },
  })

  const openEdit = (item: any) => {
    setSelectedKey(item.key)
    setEditValue(String(item.value ?? ''))
    setEditDesc('')
  }

  const saveEdit = () => {
    if (!selectedKey) return
    updateMutation.mutate({ key: selectedKey, value: editValue, description: editDesc || undefined })
  }

  const renderSource = (item: any) => {
    if (item.sensitive) {
      if (item.source === 'env') return <Badge variant="destructive">secret(env)</Badge>
      if (item.source === 'secret') return <Badge variant="outline">secret(file)</Badge>
      return <Badge variant="secondary">secret(unset)</Badge>
    }
    if (item.source === 'env') return <Badge variant="destructive">env</Badge>
    if (item.source === 'db') return <Badge variant="default">db</Badge>
    return <Badge variant="secondary">default</Badge>
  }

  const categories = React.useMemo(() => {
    const set = new Set<string>()
    configItems?.forEach((i: any) => set.add(i.category || 'General'))
    return ['ALL', ...Array.from(set)]
  }, [configItems])

  const filteredItems = React.useMemo(() => {
    return (configItems || []).filter((i: any) => {
      const matchSearch =
        i.key.toLowerCase().includes(search.toLowerCase()) ||
        (i.desc || '').toLowerCase().includes(search.toLowerCase())
      const matchCategory = categoryFilter === 'ALL' || i.category === categoryFilter
      return matchSearch && matchCategory
    })
  }, [configItems, search, categoryFilter])

  return (
    <div className="space-y-6 max-w-5xl">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Moon className="w-4 h-4" />
            Theme
          </CardTitle>
          <CardDescription>대시보드 테마를 설정합니다</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3">
            <Button variant="default" className="gap-2">
              <Moon className="w-4 h-4" />
              다크 모드
            </Button>
            <Button variant="outline" className="gap-2" disabled>
              <Sun className="w-4 h-4" />
              라이트 모드 (준비 중)
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <SettingsIcon className="w-4 h-4" />
            System Configuration
          </CardTitle>
          <CardDescription>env &gt; db &gt; default 우선순위</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2 items-center">
            <Input
              placeholder="키/설명 검색"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="max-w-sm"
            />
            <select
              className="border border-border rounded-md px-2 py-2 text-sm bg-card text-white [&>option]:bg-card [&>option]:text-white"
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
            >
              {categories.map((c) => (
                <option key={c} value={c} className="bg-card text-white">
                  {c}
                </option>
              ))}
            </select>
          </div>

          {isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" />
              불러오는 중...
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm border border-white/5 rounded-md">
                <thead className="bg-white/5">
                  <tr>
                    <th className="px-3 py-2 text-left text-muted-foreground">Key</th>
                    <th className="px-3 py-2 text-left text-muted-foreground">Value</th>
                    <th className="px-3 py-2 text-left text-muted-foreground">Source</th>
                    <th className="px-3 py-2 text-left text-muted-foreground">Default</th>
                    <th className="px-3 py-2 text-left text-muted-foreground">Category</th>
                    <th className="px-3 py-2 text-left text-muted-foreground">Desc</th>
                    <th className="px-3 py-2 text-left text-muted-foreground">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((item: any) => {
                    const displayValue = item.sensitive
                      ? item.source === 'default'
                        ? '(unset)'
                        : '***'
                      : String(item.value)
                    return (
                      <tr key={item.key} className="border-t border-white/5">
                        <td className="px-3 py-2 font-mono text-xs text-white">{item.key}</td>
                        <td className="px-3 py-2 text-white">{displayValue}</td>
                        <td className="px-3 py-2">{renderSource(item)}</td>
                        <td className="px-3 py-2 text-muted-foreground text-xs">{String(item.default ?? '')}</td>
                        <td className="px-3 py-2 text-muted-foreground">{item.category}</td>
                        <td className="px-3 py-2 text-muted-foreground text-xs">{item.desc}</td>
                        <td className="px-3 py-2">
                          {item.sensitive ? (
                            <Badge variant="outline" className="gap-1 text-xs">
                              <Lock className="w-3 h-3" />
                              secret
                            </Badge>
                          ) : item.source === 'env' ? (
                            <Badge variant="outline" className="gap-1 text-xs">
                              <AlertTriangle className="w-3 h-3" />
                              env
                            </Badge>
                          ) : (
                            <Button variant="ghost" size="sm" className="gap-1" onClick={() => openEdit(item)}>
                              <Pencil className="w-3 h-3" />
                              Edit
                            </Button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!selectedKey} onOpenChange={(open: boolean) => !open && setSelectedKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>설정 수정</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Key</Label>
              <Input value={selectedKey || ''} disabled className="bg-white/5" />
            </div>
            <div>
              <Label>Value</Label>
              <Input value={editValue} onChange={(e) => setEditValue(e.target.value)} />
            </div>
            <div>
              <Label>설명 (선택)</Label>
              <Input
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
                placeholder="DB description 필드에 저장 (옵션)"
              />
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setSelectedKey(null)}>
              취소
            </Button>
            <Button onClick={saveEdit} disabled={updateMutation.isPending}>
              {updateMutation.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              저장
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function FactorsTab() {
  const [factors, setFactors] = useState<Factor[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchFactors = async () => {
      try {
        const data = await getFactors()
        setFactors(data)
      } catch (err: any) {
        console.error('Failed to fetch factors:', err)
        setError('팩터 정보를 불러오는데 실패했습니다.')
      } finally {
        setLoading(false)
      }
    }
    fetchFactors()
  }, [])

  const groupedFactors = factors.reduce((acc, factor) => {
    const category = factor.category || '기타'
    if (!acc[category]) {
      acc[category] = []
    }
    acc[category].push(factor)
    return acc
  }, {} as Record<string, Factor[]>)

  const categoryOrder = ['Buying', 'Selling', 'Risk', 'Strategy', 'General']

  if (loading)
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    )

  if (error)
    return (
      <div className="flex items-center justify-center h-64 text-red-500">
        <AlertTriangle className="w-6 h-6 mr-2" />
        {error}
      </div>
    )

  return (
    <div className="space-y-6">
      {/* Guide */}
      <Card className="bg-blue-500/10 border-blue-500/20">
        <CardContent className="p-4">
          <h3 className="font-medium text-blue-400 mb-2">설정값 변경 방법</h3>
          <p className="text-sm text-blue-300/80 mb-3">
            설정값을 변경하려면 <code className="bg-blue-500/20 px-1 rounded">shared/config.py</code> 파일의{' '}
            <code className="bg-blue-500/20 px-1 rounded">_defaults</code> 딕셔너리를 수정하세요.
          </p>
          <div className="text-sm text-blue-300/80 space-y-1">
            <p>
              <strong>단일 백테스트:</strong>{' '}
              <code className="bg-blue-500/20 px-1 rounded">python utilities/backtest_gpt_v2.py --days 180</code>
            </p>
            <p>
              <strong>그리드 최적화:</strong>{' '}
              <code className="bg-blue-500/20 px-1 rounded">
                python utilities/auto_optimize_backtest_gpt_v2.py --days 180
              </code>
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Factor cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {categoryOrder.map((category) => {
          const categoryFactors = groupedFactors[category]
          if (!categoryFactors) return null

          return (
            <Card key={category}>
              <CardHeader className="py-3 px-5 bg-white/5 border-b border-white/5">
                <CardTitle className="text-sm font-medium">{category}</CardTitle>
              </CardHeader>
              <CardContent className="p-0 divide-y divide-white/5">
                {categoryFactors.map((f) => (
                  <div key={f.key} className="px-5 py-3 hover:bg-white/[0.02] transition-colors">
                    <div className="flex justify-between items-start mb-1">
                      <span className="font-mono text-xs text-white">{f.key}</span>
                      <Badge variant="info">{String(f.value)}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">{f.desc}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          )
        })}

        {/* Remaining categories */}
        {Object.keys(groupedFactors)
          .filter((c) => !categoryOrder.includes(c))
          .map((category) => (
            <Card key={category}>
              <CardHeader className="py-3 px-5 bg-white/5 border-b border-white/5">
                <CardTitle className="text-sm font-medium">{category}</CardTitle>
              </CardHeader>
              <CardContent className="p-0 divide-y divide-white/5">
                {groupedFactors[category].map((f) => (
                  <div key={f.key} className="px-5 py-3 hover:bg-white/[0.02] transition-colors">
                    <div className="flex justify-between items-start mb-1">
                      <span className="font-mono text-xs text-white">{f.key}</span>
                      <Badge variant="secondary">{String(f.value)}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">{f.desc}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
      </div>
    </div>
  )
}

export default SettingsPage
