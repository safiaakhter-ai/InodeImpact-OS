import { titleCase } from './utils.js';
console.log(titleCase('atlas operations'));
fetch('../config/settings.json').then(response => response.json()).then(console.log);
