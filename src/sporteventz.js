// scrapers/sporteventz.js
// SportEventz scraper with Puppeteer support for VPS.
// This version uses Puppeteer for reliable scraping of JavaScript-rendered content.
/**
 * VPS SportEventz Scraper
 *
 * Uses Puppeteer for browser automation to handle JavaScript-rendered content.
 * Can be run as a standalone service or integrated into the main VPS server.
 *
 * Exports:
 * - fetchSportEventzFixtures({ date }) for football (filtered)
 * - fetchTennisFixtures({ date }) for tennis (all matches)
 * - scrapeAll({ date }) returns both filtered football and all tennis
 *
 * When run directly, scrapes both sports and writes output to sportevent_schedule.json
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

// ---------- Configuration ----------

const BASE_URL = 'https://www.sporteventz.com';
const SOCCER_URL = `${BASE_URL}/soccer`;
const TENNIS_URL = `${BASE_URL}/tennis`;
const DEFAULT_TIMEOUT = 30000;
const SCROLL_PAUSE_TIME = 1500;
const MAX_SCROLL_ATTEMPTS = 10;

// Known TV channels for football
const TV_CHANNELS = [
  'Sky Sports Main Event',
  'Sky Sports Premier League',
  'Sky Sports Football',
  'Sky Sports',
  'TNT Sports 1',
  'TNT Sports 2',
  'TNT Sports 3',
  'TNT Sports 4',
  'TNT Sports',
  'BBC One',
  'BBC Two',
  'BBC iPlayer',
  'ITV1',
  'ITV4',
  'ITVX',
  'Channel 4',
  'Amazon Prime Video',
  'Amazon Prime',
  'Premier Sports 1',
  'Premier Sports 2',
  'Premier Sports',
  'BT Sport 1',
  'BT Sport 2',
  'BT Sport 3',
  'LaLigaTV',
  'FreeSports',
  'discovery+',
  'DAZN',
  'ESPN',
  'ESPN+',
  'beIN Sports',
  'Paramount+',
  'Peacock',
  'fuboTV',
  'CBS Sports',
  'Eurosport',
  'Viaplay',
  'SuperSport'
];

// ---------- Football Filtering Rules ----------

const ALLOWED_FOOTBALL_LEAGUES = new Set([
  "Premier League",
  "Serie A",
  "La Liga",
  "Bundesliga",
  "Ligue 1",
  "UEFA Champions League",
  "UEFA Europa League",
  "UEFA Europa Conference League",
  "UEFA Euro",
  "FA Cup",
  "League Cup",
  "FIFA World Cup",
  "International Friendly"
]);

const PREMIER_LEAGUE_TEAMS = new Set([
  "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
  "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
  "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham hotspur",
  "west ham united", "wolverhampton"
]);

const ALLOWED_TEAMS_PER_LEAGUE = {
  "Premier League": PREMIER_LEAGUE_TEAMS,
  "Serie A": new Set(["inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"]),
  "La Liga": new Set(["barcelona", "real madrid", "atletico madrid"]),
  "Bundesliga": new Set(["bayern munich", "borussia dortmund", "bayer leverkusen"]),
  "Ligue 1": new Set(["psg", "paris saint-germain", "olympique marseille", "marseille"]),
  "FA Cup": PREMIER_LEAGUE_TEAMS,
  "League Cup": PREMIER_LEAGUE_TEAMS
};

// Helper to check if a football fixture should be included
function shouldIncludeFootballFixture(homeTeam, awayTeam, competition) {
  // If competition is explicitly listed as allowed, we keep it
  if (competition && ALLOWED_FOOTBALL_LEAGUES.has(competition)) {
    // For specific leagues, check teams if there's a whitelist
    const allowedTeams = ALLOWED_TEAMS_PER_LEAGUE[competition];
    if (allowedTeams) {
      const homeLower = homeTeam.toLowerCase();
      const awayLower = awayTeam.toLowerCase();
      // If either team is in the allowed set, keep it
      return allowedTeams.has(homeLower) || allowedTeams.has(awayLower);
    }
    // For other allowed competitions (e.g. UCL), keep all
    return true;
  }
  
  // Fallback: if competition is null, try to match team names against allowed teams
  // (useful when competition is not detected)
  const homeLower = homeTeam.toLowerCase();
  const awayLower = awayTeam.toLowerCase();
  for (const league in ALLOWED_TEAMS_PER_LEAGUE) {
    const teamsSet = ALLOWED_TEAMS_PER_LEAGUE[league];
    if (teamsSet.has(homeLower) || teamsSet.has(awayLower)) {
      return true;
    }
  }
  return false;
}

// Shared browser instance
let browser = null;

// ---------- Logging ----------

function log(msg) {
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] [SPORTEVENTZ-VPS] ${msg}`);
}

// ---------- Browser Management ----------

async function getBrowser() {
  if (browser && browser.isConnected()) {
    return browser;
  }
  browser = await puppeteer.launch({
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--disable-features=site-per-process' // helps on GitHub Actions
    ]
  });
  return browser;
}

// ---------- Core Scraping Function (generic) ----------

/**
 * Generic page scraper for a given URL and sport type.
 * @param {string} url - The page URL to scrape
 * @param {string} sport - 'football' or 'tennis'
 * @returns {Promise<Array>} raw fixtures array from page evaluation
 */
async function scrapeSportPage(url, sport) {
  let page = null;
  try {
    const browserInstance = await getBrowser();
    page = await browserInstance.newPage();
    
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
    
    await page.goto(url, {
      waitUntil: 'networkidle2',
      timeout: DEFAULT_TIMEOUT
    });
    
    // Wait for body
    await page.waitForSelector('body', { timeout: 10000 });
    
    // Accept cookies if needed
    try {
      const cookieButton = await page.$('button[id*="accept"], button[class*="accept"], [class*="cookie"] button, .consent-button, #accept-cookies');
      if (cookieButton) {
        await cookieButton.click();
        await new Promise(resolve => setTimeout(resolve, 1000));
        log('Accepted cookies');
      }
    } catch (e) {
      // ignore
    }
    
    // Scroll to load dynamic content
    let previousHeight = 0;
    let scrollAttempts = 0;
    while (scrollAttempts < MAX_SCROLL_ATTEMPTS) {
      const currentHeight = await page.evaluate(() => document.body.scrollHeight);
      if (currentHeight === previousHeight) break;
      previousHeight = currentHeight;
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await new Promise(resolve => setTimeout(resolve, SCROLL_PAUSE_TIME));
      scrollAttempts++;
    }
    log(`Scrolled ${scrollAttempts} times for ${sport}`);
    
    // Extract fixtures
    const fixtures = await page.evaluate((TV_CHANNELS, sportType) => {
      const results = [];
      const fixtureSelectors = [
        '.event', '.match', '.fixture', '.game',
        '[class*="event"]', '[class*="match"]', '[class*="fixture"]',
        'table tbody tr', '.schedule-item', '.listing-item'
      ];
      
      for (const selector of fixtureSelectors) {
        const elements = document.querySelectorAll(selector);
        
        elements.forEach(el => {
          try {
            const text = el.innerText || el.textContent || '';
            const textLower = text.toLowerCase();
            
            // Skip other sports if we are targeting a specific one
            if (sportType === 'football') {
              if (textLower.includes('tennis') || textLower.includes('basketball') ||
                  textLower.includes('cricket') || textLower.includes('rugby') ||
                  textLower.includes('golf')) {
                return;
              }
            }
            
            // Extract teams
            let homeTeam = '';
            let awayTeam = '';
            
            const homeEl = el.querySelector('.home-team, .home, [class*="home"]');
            const awayEl = el.querySelector('.away-team, .away, [class*="away"]');
            if (homeEl) homeTeam = homeEl.innerText.trim();
            if (awayEl) awayTeam = awayEl.innerText.trim();
            
            const teamEls = el.querySelectorAll('.team, .team-name, [class*="team"]');
            if (teamEls.length >= 2 && (!homeTeam || !awayTeam)) {
              homeTeam = teamEls[0].innerText.trim();
              awayTeam = teamEls[1].innerText.trim();
            }
            
            // Fallback vs pattern
            if (!homeTeam || !awayTeam) {
              const vsMatch = text.match(/([A-Za-z\s\-'\.0-9]+)\s+(?:v|vs|versus|–|-)\s+([A-Za-z\s\-'\.0-9]+)/i);
              if (vsMatch) {
                homeTeam = vsMatch[1].trim();
                awayTeam = vsMatch[2].trim();
              }
            }
            
            // Clean names
            homeTeam = homeTeam.replace(/\b(fc|afc|cf|sc|ac)\b/gi, '').replace(/\s+/g, ' ').trim();
            awayTeam = awayTeam.replace(/\b(fc|afc|cf|sc|ac)\b/gi, '').replace(/\s+/g, ' ').trim();
            
            if (!homeTeam || !awayTeam) return;
            
            // Extract date/time
            let kickoffUtc = null;
            const timeEl = el.querySelector('time, [datetime], .time, .date, .kickoff');
            if (timeEl) {
              kickoffUtc = timeEl.getAttribute('datetime') || timeEl.innerText.trim() || null;
            }
            if (!kickoffUtc) {
              const dateMatch = text.match(/(\d{1,2}[\/\-\.]\d{1,2}(?:[\/\-\.]\d{2,4})?)/);
              const timeMatch = text.match(/(\d{1,2}[:\.]?\d{2}\s*(am|pm|GMT|BST|CET|UTC)?)/i);
              if (dateMatch || timeMatch) {
                kickoffUtc = [dateMatch?.[1], timeMatch?.[1]].filter(Boolean).join(' ');
              }
            }
            
            // Extract competition
            let competition = null;
            const compEl = el.querySelector('.competition, .league, .tournament, [class*="competition"], [class*="league"]');
            if (compEl) competition = compEl.innerText.trim();
            
            // Extract TV channels
            const channels = [];
            for (const channel of TV_CHANNELS) {
              if (textLower.includes(channel.toLowerCase())) {
                channels.push(channel);
              }
            }
            const channelEls = el.querySelectorAll('.channel, .broadcaster, .tv, .stream, [class*="channel"], [class*="broadcaster"], [class*="tv"]');
            channelEls.forEach(chEl => {
              const chText = chEl.innerText.trim();
              if (chText && !channels.includes(chText)) {
                const chParts = chText.split(/[,;\/\n]/).map(c => c.trim()).filter(c => c);
                chParts.forEach(ch => { if (!channels.includes(ch) && ch.length > 1) channels.push(ch); });
              }
            });
            
            // Satellite info
            const satEl = el.querySelector('.satellite, [class*="satellite"], [class*="sat"]');
            if (satEl) {
              const satText = satEl.innerText.trim();
              if (satText && !channels.includes(satText)) {
                channels.push(`Satellite: ${satText}`);
              }
            }
            
            results.push({
              home: homeTeam,
              away: awayTeam,
              kickoffUtc,
              competition,
              channels: [...new Set(channels.map(c => c.trim()).filter(c => c))]
            });
          } catch (e) {
            // skip malformed
          }
        });
        
        if (results.length > 0) break;
      }
      return results;
    }, TV_CHANNELS, sport);
    
    return fixtures;
    
  } catch (err) {
    log(`Error scraping ${sport} page: ${err.message}`);
    return [];
  } finally {
    if (page) await page.close().catch(() => {});
  }
}

// ---------- Public Functions ----------

/**
 * Fetch football fixtures with filtering.
 */
async function fetchSportEventzFixtures({ date } = {}) {
  log(`Fetching football fixtures${date ? ` for ${date}` : ' for today'}`);
  const rawFixtures = await scrapeSportPage(SOCCER_URL, 'football');
  
  // Apply filtering
  const filtered = rawFixtures.filter(f => 
    shouldIncludeFootballFixture(f.home, f.away, f.competition)
  );
  
  log(`Football: ${rawFixtures.length} raw, ${filtered.length} after filtering`);
  return { fixtures: filtered };
}

/**
 * Fetch tennis fixtures (all matches, no filtering).
 */
async function fetchTennisFixtures({ date } = {}) {
  log(`Fetching tennis fixtures${date ? ` for ${date}` : ' for today'}`);
  const rawFixtures = await scrapeSportPage(TENNIS_URL, 'tennis');
  log(`Tennis: ${rawFixtures.length} matches found`);
  return { fixtures: rawFixtures };
}

/**
 * Scrape both sports and return combined results.
 */
async function scrapeAll(params = {}) {
  const [footballResult, tennisResult] = await Promise.all([
    fetchSportEventzFixtures(params),
    fetchTennisFixtures(params)
  ]);
  
  // Normalize format
  const footballFixtures = (footballResult.fixtures || []).map(f => ({
    homeTeam: f.home || null,
    awayTeam: f.away || null,
    kickoffUtc: f.kickoffUtc || null,
    competition: f.competition || null,
    channels: f.channels || [],
    sport: 'football'
  }));
  
  const tennisFixtures = (tennisResult.fixtures || []).map(f => ({
    // For tennis, "home/away" represent players
    player1: f.home || null,
    player2: f.away || null,
    kickoffUtc: f.kickoffUtc || null,
    tournament: f.competition || null,
    channels: f.channels || [],
    sport: 'tennis'
  }));
  
  return {
    football: footballFixtures,
    tennis: tennisFixtures,
    total: footballFixtures.length + tennisFixtures.length,
    scrapedAt: new Date().toISOString(),
    source: 'sporteventz'
  };
}

async function healthCheck() {
  const start = Date.now();
  let page = null;
  try {
    const browserInstance = await getBrowser();
    page = await browserInstance.newPage();
    await page.goto(SOCCER_URL, { waitUntil: 'domcontentloaded', timeout: DEFAULT_TIMEOUT });
    const hasContent = await page.evaluate(() => {
      const text = document.body.innerText.toLowerCase();
      return text.includes('soccer') || text.includes('football') || text.includes('vs');
    });
    await page.close();
    return { ok: hasContent, latencyMs: Date.now() - start };
  } catch (e) {
    if (page) await page.close().catch(() => {});
    return { ok: false, latencyMs: Date.now() - start, error: e.message };
  }
}

// ---------- Module Exports ----------

module.exports = {
  scrapeAll,
  fetchSportEventzFixtures,
  fetchTennisFixtures,
  healthCheck,
  TV_CHANNELS,
  BASE_URL
};

// ---------- Standalone Execution ----------

if (require.main === module) {
  (async () => {
    console.log('SportEventz VPS Scraper - Combined Football (filtered) + Tennis');
    const health = await healthCheck();
    console.log('Health check:', health);
    
    if (!health.ok) {
      console.error('Health check failed, exiting.');
      process.exit(1);
    }
    
    console.log('\nScraping fixtures...');
    const allData = await scrapeAll();
    
    console.log(`Football fixtures: ${allData.football.length}`);
    console.log(`Tennis fixtures: ${allData.tennis.length}`);
    
    const outputPath = path.join(__dirname, 'sportevent_schedule.json');
    fs.writeFileSync(outputPath, JSON.stringify(allData, null, 2));
    console.log(`\nResults written to ${outputPath}`);
    
    // Optional: close browser
    if (browser) await browser.close();
    process.exit(0);
  })();
}
