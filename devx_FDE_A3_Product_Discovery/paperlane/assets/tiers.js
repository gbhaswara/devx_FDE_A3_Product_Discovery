
(function(){
  var root = document.body.getAttribute('data-root') || '';
  function fmt(n){return '\u0e3f' + Number(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}
  document.querySelectorAll('[data-sku]').forEach(function(el){
    if (el.getAttribute('data-sale') === '1') { el.textContent = 'Not available on sale items'; return; }
    fetch(root + 'api/pricing/' + el.getAttribute('data-sku') + '.json')
      .then(function(r){ if(!r.ok) throw new Error('none'); return r.json(); })
      .then(function(d){
        if(!d.tiers || !d.tiers.length){ el.textContent = 'No volume pricing'; return; }
        el.innerHTML = d.tiers.map(function(t){ return '<span class="tier">' + t.min_qty + '+ ' + d.unit + 's: <b>' + fmt(t.unit_price) + '</b></span>'; }).join(' &middot; ');
      })
      .catch(function(){ el.textContent = 'No volume pricing'; });
  });
})();
