/**
 * AWS Cost Manager - Frontend Logic
 */

let currentToken = localStorage.getItem('jwt');
let currentUserRole = null;
let rawSummaryData = []; 
let flatTableData = [];

// Filters state
let activeServiceFilter = 'ALL';
let activeRegionFilter = 'ALL';
let activeSearchFilter = '';
let isGroupedView = true;

// Chart instances
let barChartInst = null;
let pieChartInst = null;

// Pagination
let currentPage = 1;
const rowsPerPage = 12; // Reduced slightly for better fit in light theme
const AWS_COLORS = ['#ff9900', '#232f3e', '#007eb9', '#d13212', '#10b981', '#8b5cf6', '#06b6d4', '#ec4899'];

// Formatters
const USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

// Elements
const loginView = document.getElementById('login-view');
const dashboardView = document.getElementById('dashboard-view');
const statusContainer = document.getElementById('status-container');
const dashboardWidgets = document.getElementById('dashboard-widgets');
const accountsSelect = document.getElementById('account-select');

// === INIT ===
document.addEventListener('DOMContentLoaded', () => {
    if (currentToken) showDashboard();
    else showLogin();
    
    const today = new Date();
    const firstDayStr = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().split('T')[0];
    const todayStr = today.toISOString().split('T')[0];
    document.getElementById('start-date').value = firstDayStr;
    document.getElementById('end-date').value = todayStr;
});

// === AUTH ===
document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = document.getElementById('username').value;
    const p = document.getElementById('password').value;
    const errObj = document.getElementById('login-error');
    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: u, password: p })
        });
        const data = await res.json();
        if (res.ok) {
            currentToken = data.token;
            currentUserRole = data.role;
            localStorage.setItem('jwt', currentToken);
            document.getElementById('user-display').textContent = `Hola, ${u}`;
            showDashboard();
        } else {
            errObj.textContent = data.message;
            errObj.classList.remove('hidden-view');
        }
    } catch (e) {
        errObj.textContent = "Error de conexión con el servidor.";
        errObj.classList.remove('hidden-view');
    }
});

document.getElementById('btn-logout').addEventListener('click', () => {
    localStorage.removeItem('jwt');
    currentToken = null;
    showLogin();
});

function showLogin() { loginView.classList.remove('hidden-view'); dashboardView.classList.add('hidden-view'); }
function showDashboard() { loginView.classList.add('hidden-view'); dashboardView.classList.remove('hidden-view'); loadAccounts(); }

// === ACCOUNTS ===
async function doAuthFetch(url, options = {}) {
    if(!options.headers) options.headers = {};
    options.headers['Authorization'] = `Bearer ${currentToken}`;
    const res = await fetch(url, options);
    if(res.status === 401) { localStorage.removeItem('jwt'); location.reload(); }
    return res;
}

async function loadAccounts() {
    try {
        const res = await doAuthFetch('/api/accounts');
        const data = await res.json();
        accountsSelect.innerHTML = '<option value="" disabled selected>Seleccione una cuenta...</option>';
        const listUl = document.getElementById('accounts-list');
        listUl.innerHTML = '';
        if (data.length === 0) listUl.innerHTML = '<li class="text-sm text-slate-500">No hay cuentas configuradas</li>';
        
        data.forEach(acc => {
            const opt = document.createElement('option');
            opt.value = acc.alias_cuenta;
            opt.textContent = `${acc.alias_cuenta} (${acc.region})`;
            accountsSelect.appendChild(opt);
            
            const li = document.createElement('li');
            li.className = "flex justify-between items-center bg-gray-50 p-3 rounded border border-gray-300";
            li.innerHTML = `
                <div><div class="text-sm text-aws-text font-bold">${acc.alias_cuenta}</div>
                <div class="text-xs text-gray-500">${acc.access_key}</div></div>
                <button onclick="deleteAccount('${acc.alias_cuenta}')" class="text-red-600 hover:text-red-700 font-bold px-2">Eliminar</button>
            `;
            listUl.appendChild(li);
        });
        if (data.length > 0) accountsSelect.selectedIndex = 1;
    } catch(e) { console.error(e); }
}

document.getElementById('form-add-account').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {
        alias_cuenta: document.getElementById('acc-alias').value,
        access_key: document.getElementById('acc-access').value,
        secret_key: document.getElementById('acc-secret').value,
        region: document.getElementById('acc-region').value
    };
    const errDiv = document.getElementById('modal-error');
    const res = await doAuthFetch('/api/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    if (res.ok) {
        document.getElementById('form-add-account').reset();
        errDiv.classList.add('hidden-view');
        loadAccounts();
    } else {
        const json = await res.json();
        errDiv.textContent = json.message;
        errDiv.classList.remove('hidden-view');
    }
});

async function deleteAccount(alias) {
    if(!confirm(`¿Eliminar cuenta aws: ${alias}?`)) return;
    await doAuthFetch(`/api/accounts/${alias}`, { method: 'DELETE' });
    loadAccounts();
}

// Modal Accounts
const modalBd = document.getElementById('modal-backdrop');
const modalPanel = document.getElementById('modal-accounts');
document.getElementById('btn-manage-accounts').addEventListener('click', () => {
    modalBd.classList.remove('hidden-view');
    setTimeout(() => {
        modalPanel.classList.remove('scale-95', 'opacity-0');
        modalPanel.classList.add('scale-100', 'opacity-100');
    }, 10);
});
document.getElementById('btn-close-modal').addEventListener('click', () => {
    modalPanel.classList.add('scale-95', 'opacity-0');
    modalPanel.classList.remove('scale-100', 'opacity-100');
    setTimeout(() => { modalBd.classList.add('hidden-view'); }, 200);
});

// === FETCH DATA ===
document.getElementById('btn-fetch-costs').addEventListener('click', async () => {
    const alias = accountsSelect.value;
    const sd = document.getElementById('start-date').value;
    const ed = document.getElementById('end-date').value;
    if(!alias) return alert("Seleccione una cuenta AWS");
    
    statusContainer.classList.remove('hidden-view');
    dashboardWidgets.classList.add('hidden-view');
    
    try {
        const res = await doAuthFetch(`/api/costs/summary?alias_cuenta=${alias}&start_date=${sd}&end_date=${ed}`);
        const data = await res.json();
        
        if(!res.ok) throw new Error(data.message);
        
        rawSummaryData = data.summary;
        populateFilters();
        processDataForViews();
        
        statusContainer.classList.add('hidden-view');
        dashboardWidgets.classList.remove('hidden-view');
    } catch(e) {
        statusContainer.classList.add('hidden-view');
        alert("Error cargando costos: " + e.message);
    }
});

function populateFilters() {
    const serviceSelect = document.getElementById('service-filter');
    serviceSelect.innerHTML = '<option value="ALL">Todos los Servicios</option>';
    const distinctServices = [...new Set(rawSummaryData.map(item => item.servicio))].sort();
    distinctServices.forEach(srv => {
        const opt = document.createElement('option');
        opt.value = srv; opt.textContent = srv;
        serviceSelect.appendChild(opt);
    });

    const regionSelect = document.getElementById('region-filter');
    if (regionSelect) {
        regionSelect.innerHTML = '<option value="ALL">Todas las Regiones</option>';
        const distinctRegions = new Set();
        rawSummaryData.forEach(item => {
            item.breakdown.forEach(b => distinctRegions.add(b.region || 'Global / Sin Región'));
        });
        [...distinctRegions].sort().forEach(reg => {
            const opt = document.createElement('option');
            opt.value = reg; opt.textContent = reg;
            regionSelect.appendChild(opt);
        });
    }
}

// === PIPELINE AND FILTERING ===
document.getElementById('service-filter').addEventListener('change', (e) => {
    activeServiceFilter = e.target.value;
    processDataForViews();
});

const reqFilterObj = document.getElementById('region-filter');
if (reqFilterObj) {
    reqFilterObj.addEventListener('change', (e) => {
        activeRegionFilter = e.target.value;
        processDataForViews();
    });
}

document.getElementById('search-filter').addEventListener('input', (e) => {
    activeSearchFilter = e.target.value.toLowerCase();
    processDataForViews();
});

// View Toggle
const btnGrouped = document.getElementById('view-grouped');
const btnDetailed = document.getElementById('view-detailed');

btnGrouped.addEventListener('click', () => {
    isGroupedView = true;
    btnGrouped.classList.add('bg-white', 'text-gray-900', 'shadow-sm', 'border', 'border-gray-300', 'pointer-events-none');
    btnGrouped.classList.remove('text-gray-600', 'font-medium');
    btnGrouped.classList.add('font-bold');
    
    btnDetailed.classList.remove('bg-white', 'text-gray-900', 'shadow-sm', 'border', 'border-gray-300', 'pointer-events-none', 'font-bold');
    btnDetailed.classList.add('text-gray-600', 'font-medium');
    
    processDataForViews();
});

btnDetailed.addEventListener('click', () => {
    isGroupedView = false;
    btnDetailed.classList.add('bg-white', 'text-gray-900', 'shadow-sm', 'border', 'border-gray-300', 'pointer-events-none');
    btnDetailed.classList.remove('text-gray-600', 'font-medium');
    btnDetailed.classList.add('font-bold');
    
    btnGrouped.classList.remove('bg-white', 'text-gray-900', 'shadow-sm', 'border', 'border-gray-300', 'pointer-events-none', 'font-bold');
    btnGrouped.classList.add('text-gray-600', 'font-medium');
    
    processDataForViews();
});


function processDataForViews() {
    let totalsByService = {};
    let datesSet = new Set();
    let barDatasets = {};
    flatTableData = [];
    let grandTotal = 0;
    
    let serviceColorMap = {}; let colorIdx = 0;

    // Filter by Service
    let filteredData = rawSummaryData;
    if (activeServiceFilter !== 'ALL') {
        filteredData = filteredData.filter(d => d.servicio === activeServiceFilter);
    }
    
    // Summary Grouping: Resource Name + Service
    const resourceSummaryMap = {};

    filteredData.forEach(day => {
        datesSet.add(day.fecha);
        
        let matchingBreakdowns = day.breakdown.filter(b => {
            let matchedRegion = (activeRegionFilter === 'ALL' || (b.region || 'Global / Sin Región') === activeRegionFilter);
            let matchedSearch = !activeSearchFilter || b.resource_name.toLowerCase().includes(activeSearchFilter);
            return matchedRegion && matchedSearch;
        });
        
        matchingBreakdowns.forEach(b => {
            grandTotal += b.cost;
            totalsByService[day.servicio] = (totalsByService[day.servicio] || 0) + b.cost;
            
            // Charts
            if(!barDatasets[day.servicio]) {
                if(!serviceColorMap[day.servicio]) {
                    serviceColorMap[day.servicio] = AWS_COLORS[colorIdx % AWS_COLORS.length];
                    colorIdx++;
                }
                barDatasets[day.servicio] = {};
            }
            barDatasets[day.servicio][day.fecha] = (barDatasets[day.servicio][day.fecha] || 0) + b.cost;
            
            if (isGroupedView) {
                // Group by Resource + Service
                const key = `${b.resource_name}|${day.servicio}`;
                if (!resourceSummaryMap[key]) {
                    resourceSummaryMap[key] = {
                        type: 'SUMMARY',
                        date: 'Acumulado',
                        service: day.servicio,
                        context: b.resource_name,
                        cost: 0,
                        rawDetails: []
                    };
                }
                resourceSummaryMap[key].cost += b.cost;
                resourceSummaryMap[key].rawDetails.push({...b, fecha: day.fecha});
            } else {
                // Detailed (Day by day)
                flatTableData.push({
                    type: 'DETAILED',
                    date: day.fecha,
                    service: day.servicio,
                    context: b.resource_name,
                    usage_type: b.usage_type,
                    operation: b.operation,
                    region: b.region,
                    cost: b.cost
                });
            }
        });
    });

    if (isGroupedView) {
        flatTableData = Object.values(resourceSummaryMap);
    }
    
    document.getElementById('widget-total-cost').textContent = USD.format(grandTotal);
    flatTableData.sort((a,b) => b.cost - a.cost); 
    
    const sortedDates = Array.from(datesSet).sort();
    renderBarChart(sortedDates, barDatasets, serviceColorMap);
    renderPieChart(totalsByService, serviceColorMap);
    
    currentPage = 1;
    renderTable();
}

function renderBarChart(dates, barDatasets, colorMap) {
    if(barChartInst) barChartInst.destroy();
    const datasets = Object.keys(barDatasets).map(srv => {
        const dataArr = dates.map(d => barDatasets[srv][d] || 0);
        return {
            label: srv, data: dataArr,
            backgroundColor: colorMap[srv] + 'b3', borderColor: colorMap[srv],
            borderWidth: 1, fill: true
        }
    });

    const ctx = document.getElementById('barChart').getContext('2d');
    Chart.defaults.color = '#16191f';
    Chart.defaults.font.family = "'Public Sans', sans-serif";
    barChartInst = new Chart(ctx, {
        type: 'bar',
        data: { labels: dates, datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { 
                tooltip: { 
                    mode: 'index', 
                    intersect: false,
                    backgroundColor: '#232f3e',
                    titleColor: '#ffffff'
                }, 
                legend: { position: 'top', labels: { boxWidth: 12, usePointStyle: true, font: { weight: 'bold' } } } 
            },
            scales: { 
                x: { stacked: true, grid: { color: '#eaeded' } }, 
                y: { stacked: true, grid: { color: '#eaeded' }, ticks: { callback: value => '$' + value } } 
            }
        }
    });
}

function renderPieChart(totals, colorMap) {
    if(pieChartInst) pieChartInst.destroy();
    const labels = Object.keys(totals);
    const data = labels.map(l => totals[l]);
    const ctx = document.getElementById('pieChart').getContext('2d');
    pieChartInst = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: labels.map(l => colorMap[l] + 'cc'),
                borderColor: labels.map(l => colorMap[l]),
                borderWidth: 2, hoverOffset: 4
            }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, cutout: '70%'}
    });
}

// === PAGINATOR AND TABLE === //
function renderTable() {
    const totalPages = Math.ceil(flatTableData.length / rowsPerPage) || 1;
    document.getElementById('page-total').textContent = totalPages;
    document.getElementById('page-current').textContent = currentPage;
    
    const btnP = document.getElementById('btn-prev-page');
    const btnN = document.getElementById('btn-next-page');
    btnP.disabled = (currentPage === 1);
    btnN.disabled = (currentPage === totalPages);
    
    const tbody = document.getElementById('table-body');
    tbody.innerHTML = '';
    
    const startIdx = (currentPage - 1) * rowsPerPage;
    const slice = flatTableData.slice(startIdx, startIdx + rowsPerPage);
    
    slice.forEach((r, idx) => {
        const tr = document.createElement('tr');
        tr.className = "hover:bg-gray-50 transition-colors";
        
        let contextHTML = `
            <td class="px-6 py-3 font-semibold text-gray-900" title="${r.context}">${r.context}</td>
            <td class="px-6 py-3 text-gray-500 text-xs truncate max-w-[150px]" title="${r.usage_type}">${r.usage_type}</td>
            <td class="px-6 py-3 text-gray-500 text-xs">${r.operation || 'N/A'}</td>
            <td class="px-6 py-3 text-xs">
                <span class="bg-gray-100 text-gray-700 px-2 py-1 rounded border border-gray-300 font-medium">${r.region || 'Global'}</span>
            </td>`;
            
        if (r.type === 'SUMMARY') {
            contextHTML = `
            <td class="px-6 py-3">
                <button onclick="openDrilldown('${r.context.replace(/'/g, "\\'")}', '${r.service}')" class="text-xs px-3 py-1 bg-white text-aws-link border border-aws-link rounded hover:bg-blue-50 font-bold transition-colors">
                    Desglosar (${r.rawDetails.length} registros)
                </button>
            </td>
            <td class="px-6 py-3 font-medium text-gray-800" title="${r.context}">${r.context}</td>
            <td class="px-6 py-3 text-gray-400 text-center">-</td>
            <td class="px-6 py-3 text-center">
                <span class="text-gray-400">-</span>
            </td>`;
        }

        tr.innerHTML = `
            <td class="px-6 py-3 whitespace-nowrap text-gray-500 font-medium">${r.date}</td>
            <td class="px-6 py-3">
                <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-aws-navy text-white text-uppercase">${r.service}</span>
            </td>
            ${contextHTML}
            <td class="px-6 py-3 text-right font-bold text-gray-900">${USD.format(r.cost)}</td>
        `;
        tbody.appendChild(tr);
    });
}

document.getElementById('btn-prev-page').addEventListener('click', () => { if(currentPage > 1) { currentPage--; renderTable(); } });
document.getElementById('btn-next-page').addEventListener('click', () => {
    const totalPages = Math.ceil(flatTableData.length / rowsPerPage);
    if(currentPage < totalPages) { currentPage++; renderTable(); }
});

// === DRILL-DOWN MODAL ===
function openDrilldown(resourceName, serviceName) {
    const key = `${resourceName}|${serviceName}`;
    const row = flatTableData.find(f => f.context === resourceName && f.service === serviceName && f.type === 'SUMMARY');
    if (!row) return;

    document.getElementById('drilldown-title').textContent = `Desglose: ${resourceName}`;
    document.getElementById('drilldown-total').textContent = USD.format(row.cost);
    
    // Summary Text generator
    const details = row.rawDetails;
    const numDays = new Set(details.map(d => d.fecha)).size;
    const summaryText = `Este recurso ha generado un costo real de <strong>${USD.format(row.cost)}</strong> distribuido en ${numDays} días de operación dentro del periodo consultado. Se detallan a continuación los conceptos específicos de facturación de AWS.`;
    document.getElementById('modal-summary-text').innerHTML = summaryText;

    // Consolidate identical usage/operation entries across days into a single detail row
    const consolidatedMap = {};
    details.forEach(d => {
        const d_key = d.usage_type + '|' + d.operation;
        if (!consolidatedMap[d_key]) {
            consolidatedMap[d_key] = { 
                name: resourceName, 
                usage: d.usage_type, 
                op: d.operation,
                region: d.region, 
                cost: 0 
            };
        }
        consolidatedMap[d_key].cost += d.cost;
    });
    
    const dtbody = document.getElementById('drilldown-tbody');
    dtbody.innerHTML = '';
    
    Object.values(consolidatedMap).sort((a,b) => b.cost - a.cost).forEach(b_data => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="px-4 py-3 text-gray-900 font-bold text-xs break-all">${b_data.name}</td>
            <td class="px-4 py-3 text-gray-500 text-xs break-all">${b_data.usage}</td>
            <td class="px-4 py-3 text-gray-500 text-xs">${b_data.op || 'N/A'}</td>
            <td class="px-4 py-3"><span class="bg-gray-100 text-gray-700 text-xs px-2 py-1 border border-gray-300 rounded font-medium">${b_data.region}</span></td>
            <td class="px-4 py-3 text-right font-bold text-gray-900 whitespace-nowrap">${USD.format(b_data.cost)}</td>
        `;
        dtbody.appendChild(tr);
    });
    
    document.getElementById('modal-drilldown').classList.remove('hidden-view');
    // Animación suave
    setTimeout(() => {
        const panel = document.getElementById('modal-drilldown-panel');
        if (panel) panel.classList.remove('scale-95', 'opacity-0');
    }, 50);
}

document.getElementById('btn-close-drilldown').addEventListener('click', () => {
    document.getElementById('modal-drilldown-panel').classList.add('scale-95', 'opacity-0');
    document.getElementById('modal-drilldown-panel').classList.remove('scale-100', 'opacity-100');
    setTimeout(() => { document.getElementById('modal-drilldown').classList.add('hidden-view'); }, 200);
});

// Exports logic continues...
function downloadExportUrl(endpoint) {
    const alias = accountsSelect.value;
    const sd = document.getElementById('start-date').value;
    const ed = document.getElementById('end-date').value;
    const srv = encodeURIComponent(activeServiceFilter);
    const reg = encodeURIComponent(activeRegionFilter);
    const search = encodeURIComponent(activeSearchFilter);
    
    fetch(`${endpoint}?alias_cuenta=${alias}&start_date=${sd}&end_date=${ed}&service=${srv}&region=${reg}&search=${search}`, { headers: { 'Authorization': `Bearer ${currentToken}` } })
    .then(async res => {
        if(!res.ok) throw new Error(await res.text()); return res.blob();
    })
    .then(blob => {
        const url = window.URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url;
        a.download = `AWS_Export_${new Date().toISOString().split('T')[0]}`;
        document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url);
    }).catch(e => alert("Error al exportar: " + e));
}
document.getElementById('btn-export-csv').addEventListener('click', () => downloadExportUrl('/api/export/csv'));
document.getElementById('btn-export-pdf').addEventListener('click', () => downloadExportUrl('/api/export/pdf'));
